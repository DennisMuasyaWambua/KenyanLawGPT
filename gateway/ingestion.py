"""Per-case document ingestion pipeline.

When a case document finishes uploading we extract its text, chunk it, embed
the chunks and add them to a per-firm vector collection. At query time the
assistant can then retrieve case-specific context to ground its legal
reasoning, alongside the general Kenya-law corpus.

The heavy lifting reuses the already-initialised RAG engine
(``law_app.signals.rag``): its Chroma client and embedding model. If the engine
isn't up yet, ingestion fails softly and the document is marked accordingly —
it can be re-ingested later.
"""
import io
import logging

from . import storage
from .models import CaseDocument

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 200


def collection_name_for_firm(firm_id):
    return f'firm_{str(firm_id).replace("-", "")}_cases'


def _extract_text(data, filename, content_type):
    name = (filename or '').lower()
    ct = (content_type or '').lower()

    if name.endswith('.pdf') or 'pdf' in ct:
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(data)) as pdf:
                return '\n'.join(page.extract_text() or '' for page in pdf.pages)
        except Exception:  # fall back to PyPDF2
            try:
                from PyPDF2 import PdfReader

                reader = PdfReader(io.BytesIO(data))
                return '\n'.join(page.extract_text() or '' for page in reader.pages)
            except Exception as exc:
                raise ValueError(f'Could not read PDF: {exc}') from exc

    if name.endswith('.docx') or 'word' in ct or 'officedocument' in ct:
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(data))
        return '\n'.join(p.text for p in doc.paragraphs)

    # Plain text / markdown / anything decodable.
    try:
        return data.decode('utf-8', errors='ignore')
    except Exception as exc:
        raise ValueError(f'Unsupported document type: {exc}') from exc


def _chunk(text):
    text = ' '.join((text or '').split())
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = start + _CHUNK_SIZE
        chunks.append(text[start:end])
        start = end - _CHUNK_OVERLAP
    return chunks


def _get_rag():
    from law_app import signals

    return signals.rag


def ingest_document(document: CaseDocument):
    """Extract, chunk, embed and store one case document. Returns chunk count.

    Updates ``document.status`` and persists. Raises on hard failure after
    recording the error, so callers/tests can surface it.
    """
    rag = _get_rag()
    if rag is None or getattr(rag, 'embedding_model', None) is None:
        document.status = CaseDocument.STATUS_UPLOADED
        document.error = 'RAG engine not initialised; document queued for ingestion.'
        document.save(update_fields=['status', 'error', 'updated_at'])
        return 0

    try:
        data = storage.read_object(document.storage_key)
        text = _extract_text(data, document.filename, document.content_type)
        chunks = _chunk(text)
        if not chunks:
            raise ValueError('No extractable text in document.')

        collection = rag.chroma_client.get_or_create_collection(
            name=collection_name_for_firm(document.case.firm_id)
        )
        embeddings = rag.embedding_model.encode(chunks).tolist()
        ids = [f'{document.id}-{i}' for i in range(len(chunks))]
        metadatas = [
            {
                'case_id': str(document.case_id),
                'document_id': str(document.id),
                'filename': document.filename,
                'title': document.case.title,
                'url': f'case://{document.case_id}/{document.filename}',
            }
            for _ in chunks
        ]
        collection.add(
            ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas
        )

        document.status = CaseDocument.STATUS_INGESTED
        document.chunk_count = len(chunks)
        document.error = ''
        document.save(update_fields=['status', 'chunk_count', 'error', 'updated_at'])
        return len(chunks)
    except Exception as exc:
        logger.exception('Ingestion failed for document %s', document.id)
        document.status = CaseDocument.STATUS_FAILED
        document.error = str(exc)[:1000]
        document.save(update_fields=['status', 'error', 'updated_at'])
        raise
