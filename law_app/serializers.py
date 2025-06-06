from rest_framework import serializers

class ChatRequestSerializer(serializers.Serializer):
    query = serializers.CharField(help_text="User query to the Kenya Law Assistant")
    site_filter = serializers.CharField(allow_null=True, required=False, 
                                      help_text="Optional site filter: 'kenyalaw.org' or 'new.kenyalaw.org'")
    model_name = serializers.CharField(default="llama3", 
                                     help_text="Model name to use with Ollama")

class CrawlRequestSerializer(serializers.Serializer):
    max_pages = serializers.IntegerField(default=100, 
                                        help_text="Maximum number of pages to crawl")
    max_depth = serializers.IntegerField(default=3, 
                                       help_text="Maximum depth of links to follow")
    resume = serializers.BooleanField(default=True, 
                                     help_text="Whether to resume from previous crawl")

class ChatResponseSerializer(serializers.Serializer):
    response = serializers.CharField(help_text="The response from the Kenya Law Assistant")
    sources = serializers.ListField(child=serializers.DictField(), 
                                   help_text="Sources used to generate the response")
    query = serializers.CharField(help_text="Original user query")

class StatusResponseSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="Status of the operation")
    message = serializers.CharField(help_text="Additional information")
    
class SampleQuestionsSerializer(serializers.Serializer):
    questions = serializers.ListField(child=serializers.CharField(), 
                                     help_text="List of sample questions")
