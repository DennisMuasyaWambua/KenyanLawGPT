package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type Client struct {
	ID               string     `json:"id"`
	Name             string     `json:"name"`
	Email            string     `json:"email"`
	Phone            string     `json:"phone"`
	IDNumber         string     `json:"id_number"` // national ID for individuals
	KDPAConsent      bool       `json:"kdpa_consent"`
	Status           string     `json:"status"`      // lead|intake|conflict_check|engaged|active|closed
	ClientType       string     `json:"client_type"` // individual|company
	CompanyRegNumber string     `json:"company_reg_number"`
	ConflictCheckAt  *time.Time `json:"conflict_check_at,omitempty"`
	ConflictCheckBy  *string    `json:"conflict_check_by,omitempty"`
	RetainerRef      string     `json:"retainer_ref"`
	KYCCompletedAt   *time.Time `json:"kyc_completed_at,omitempty"`
	KYCRef           string     `json:"kyc_ref"`
	CreatedAt        time.Time  `json:"created_at"`
}

// StageEvent is one row of the client onboarding audit trail.
type StageEvent struct {
	ID         string    `json:"id"`
	ClientID   string    `json:"client_id"`
	FromStatus string    `json:"from_status"`
	ToStatus   string    `json:"to_status"`
	Note       string    `json:"note"`
	AdvancedBy string    `json:"advanced_by"`
	CreatedAt  time.Time `json:"created_at"`
}

type File struct {
	ID              string     `json:"id"`
	Reference       string     `json:"reference"`
	Title           string     `json:"title"`
	Description     string     `json:"description"`
	ClientID        *string    `json:"client_id"`
	ClientName      string     `json:"client_name,omitempty"`
	Status          string     `json:"status"` // intake|active|awaiting_court|appeal|closed
	PracticeArea    string     `json:"practice_area"`
	Court           string     `json:"court"`
	CourtCaseNumber string     `json:"court_case_number"`
	AssignedTo      *string    `json:"assigned_to"`
	OpenedAt        time.Time  `json:"opened_at"`
	ClosedAt        *time.Time `json:"closed_at"`
	CreatedBy       string     `json:"created_by"`
	CreatedAt       time.Time  `json:"created_at"`
	UpdatedAt       time.Time  `json:"updated_at"`
}

type FileEvent struct {
	ID        string    `json:"id"`
	FileID  string    `json:"file_id"`
	EventType string    `json:"event_type"`
	Note      string    `json:"note"`
	CreatedBy string    `json:"created_by"`
	CreatedAt time.Time `json:"created_at"`
}

type CourtDate struct {
	ID        string    `json:"id"`
	FileID  string    `json:"file_id"`
	Date      time.Time `json:"date"`
	Courtroom string    `json:"courtroom"`
	Judge     string    `json:"judge"`
	Purpose   string    `json:"purpose"`
	Reminded  bool      `json:"reminded"`
}

type Deadline struct {
	ID        string    `json:"id"`
	FileID  string    `json:"file_id"`
	Title     string    `json:"title"`
	DueAt     time.Time `json:"due_at"`
	RemindAt  time.Time `json:"remind_at"`
	Reminded  bool      `json:"reminded"`
	CreatedBy string    `json:"created_by"`
}

const fileCols = `m.id, m.reference, m.title, m.description, m.client_id, COALESCE(c.name,''),
	m.status, m.practice_area, m.court, m.court_case_number, m.assigned_to,
	m.opened_at, m.closed_at, m.created_by, m.created_at, m.updated_at`

func scanFile(row pgx.Row) (*File, error) {
	var m File
	err := row.Scan(&m.ID, &m.Reference, &m.Title, &m.Description, &m.ClientID, &m.ClientName,
		&m.Status, &m.PracticeArea, &m.Court, &m.CourtCaseNumber, &m.AssignedTo,
		&m.OpenedAt, &m.ClosedAt, &m.CreatedBy, &m.CreatedAt, &m.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return &m, nil
}

func ListFiles(ctx context.Context, tx pgx.Tx, status, search, clientID string) ([]File, error) {
	q := "SELECT " + fileCols + ` FROM files m LEFT JOIN clients c ON c.id = m.client_id WHERE 1=1`
	args := []any{}
	if status != "" {
		args = append(args, status)
		q += " AND m.status = $" + itoa(len(args))
	}
	if search != "" {
		args = append(args, "%"+search+"%")
		q += " AND (m.title ILIKE $" + itoa(len(args)) + " OR m.reference ILIKE $" + itoa(len(args)) + ")"
	}
	if clientID != "" {
		args = append(args, clientID)
		q += " AND m.client_id = $" + itoa(len(args))
	}
	q += " ORDER BY m.updated_at DESC LIMIT 200"
	rows, err := tx.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []File
	for rows.Next() {
		var m File
		if err := rows.Scan(&m.ID, &m.Reference, &m.Title, &m.Description, &m.ClientID, &m.ClientName,
			&m.Status, &m.PracticeArea, &m.Court, &m.CourtCaseNumber, &m.AssignedTo,
			&m.OpenedAt, &m.ClosedAt, &m.CreatedBy, &m.CreatedAt, &m.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

func FileByID(ctx context.Context, tx pgx.Tx, id string) (*File, error) {
	return scanFile(tx.QueryRow(ctx,
		"SELECT "+fileCols+" FROM files m LEFT JOIN clients c ON c.id = m.client_id WHERE m.id = $1", id))
}

func InsertFile(ctx context.Context, tx pgx.Tx, m *File) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO files (id, reference, title, description, client_id, status, practice_area,
		   court, court_case_number, assigned_to, created_by)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
		m.ID, m.Reference, m.Title, m.Description, m.ClientID, m.Status, m.PracticeArea,
		m.Court, m.CourtCaseNumber, m.AssignedTo, m.CreatedBy)
	return err
}

func UpdateFile(ctx context.Context, tx pgx.Tx, m *File) error {
	_, err := tx.Exec(ctx,
		`UPDATE files SET title=$2, description=$3, client_id=$4, status=$5, practice_area=$6,
		   court=$7, court_case_number=$8, assigned_to=$9,
		   closed_at = CASE WHEN $5 = 'closed' AND closed_at IS NULL THEN now()
		                    WHEN $5 <> 'closed' THEN NULL ELSE closed_at END,
		   updated_at = now()
		 WHERE id=$1`,
		m.ID, m.Title, m.Description, m.ClientID, m.Status, m.PracticeArea,
		m.Court, m.CourtCaseNumber, m.AssignedTo)
	return err
}

func InsertFileEvent(ctx context.Context, tx pgx.Tx, e *FileEvent) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO file_events (id, file_id, event_type, note, created_by) VALUES ($1,$2,$3,$4,$5)",
		e.ID, e.FileID, e.EventType, e.Note, e.CreatedBy)
	return err
}

func ListFileEvents(ctx context.Context, tx pgx.Tx, fileID string) ([]FileEvent, error) {
	rows, err := tx.Query(ctx,
		"SELECT id, file_id, event_type, note, created_by, created_at FROM file_events WHERE file_id=$1 ORDER BY created_at DESC",
		fileID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []FileEvent
	for rows.Next() {
		var e FileEvent
		if err := rows.Scan(&e.ID, &e.FileID, &e.EventType, &e.Note, &e.CreatedBy, &e.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

func InsertCourtDate(ctx context.Context, tx pgx.Tx, cd *CourtDate) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO court_dates (id, file_id, date, courtroom, judge, purpose) VALUES ($1,$2,$3,$4,$5,$6)",
		cd.ID, cd.FileID, cd.Date, cd.Courtroom, cd.Judge, cd.Purpose)
	return err
}

func InsertDeadline(ctx context.Context, tx pgx.Tx, d *Deadline) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO deadlines (id, file_id, title, due_at, remind_at, created_by) VALUES ($1,$2,$3,$4,$5,$6)",
		d.ID, d.FileID, d.Title, d.DueAt, d.RemindAt, d.CreatedBy)
	return err
}

func ListUpcoming(ctx context.Context, tx pgx.Tx, within time.Duration) ([]CourtDate, []Deadline, error) {
	horizon := time.Now().Add(within)
	var cds []CourtDate
	rows, err := tx.Query(ctx,
		"SELECT id, file_id, date, courtroom, judge, purpose, reminded FROM court_dates WHERE date BETWEEN now() AND $1 AND NOT reminded", horizon)
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var cd CourtDate
		if err := rows.Scan(&cd.ID, &cd.FileID, &cd.Date, &cd.Courtroom, &cd.Judge, &cd.Purpose, &cd.Reminded); err != nil {
			rows.Close()
			return nil, nil, err
		}
		cds = append(cds, cd)
	}
	rows.Close()
	if rows.Err() != nil {
		return nil, nil, rows.Err()
	}
	var dls []Deadline
	rows, err = tx.Query(ctx,
		"SELECT id, file_id, title, due_at, remind_at, reminded, created_by FROM deadlines WHERE remind_at <= now() AND due_at > now() AND NOT reminded")
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var d Deadline
		if err := rows.Scan(&d.ID, &d.FileID, &d.Title, &d.DueAt, &d.RemindAt, &d.Reminded, &d.CreatedBy); err != nil {
			rows.Close()
			return nil, nil, err
		}
		dls = append(dls, d)
	}
	rows.Close()
	return cds, dls, rows.Err()
}

func MarkReminded(ctx context.Context, tx pgx.Tx, table, id string) error {
	switch table {
	case "court_dates", "deadlines":
	default:
		return pgx.ErrNoRows
	}
	_, err := tx.Exec(ctx, "UPDATE "+table+" SET reminded = true WHERE id = $1", id)
	return err
}

// --- clients ---

const clientCols = "id, name, email, phone, id_number, kdpa_consent, status, client_type, " +
	"company_reg_number, conflict_check_at, conflict_check_by, retainer_ref, kyc_completed_at, kyc_ref, created_at"

func scanClient(row pgx.Row) (*Client, error) {
	var c Client
	if err := row.Scan(&c.ID, &c.Name, &c.Email, &c.Phone, &c.IDNumber, &c.KDPAConsent, &c.Status,
		&c.ClientType, &c.CompanyRegNumber, &c.ConflictCheckAt, &c.ConflictCheckBy, &c.RetainerRef,
		&c.KYCCompletedAt, &c.KYCRef, &c.CreatedAt); err != nil {
		return nil, err
	}
	return &c, nil
}

// ListClients returns clients, optionally filtered by pipeline status.
func ListClients(ctx context.Context, tx pgx.Tx, status string) ([]Client, error) {
	q := "SELECT " + clientCols + " FROM clients"
	args := []any{}
	if status != "" {
		q += " WHERE status = $1"
		args = append(args, status)
	}
	q += " ORDER BY name"
	rows, err := tx.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Client
	for rows.Next() {
		c, err := scanClient(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *c)
	}
	return out, rows.Err()
}

func ClientByID(ctx context.Context, tx pgx.Tx, id string) (*Client, error) {
	return scanClient(tx.QueryRow(ctx, "SELECT "+clientCols+" FROM clients WHERE id=$1", id))
}

func InsertClient(ctx context.Context, tx pgx.Tx, c *Client) error {
	if c.Status == "" {
		c.Status = "lead"
	}
	if c.ClientType == "" {
		c.ClientType = "individual"
	}
	_, err := tx.Exec(ctx,
		`INSERT INTO clients (id, name, email, phone, id_number, kdpa_consent, status, client_type, company_reg_number)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		c.ID, c.Name, c.Email, c.Phone, c.IDNumber, c.KDPAConsent, c.Status, c.ClientType, c.CompanyRegNumber)
	return err
}

// UpdateClientDetails edits non-pipeline fields (not status — that goes through
// AdvanceClientStage so every transition is audited).
func UpdateClientDetails(ctx context.Context, tx pgx.Tx, c *Client) error {
	_, err := tx.Exec(ctx,
		`UPDATE clients SET name=$2, email=$3, phone=$4, id_number=$5, kdpa_consent=$6,
		   client_type=$7, company_reg_number=$8 WHERE id=$1`,
		c.ID, c.Name, c.Email, c.Phone, c.IDNumber, c.KDPAConsent, c.ClientType, c.CompanyRegNumber)
	return err
}

// SetClientStage moves a client to a new status and records optional
// pipeline artifacts (retainer/KYC refs). The caller validates the transition.
func SetClientStage(ctx context.Context, tx pgx.Tx, id, toStatus, retainerRef, kycRef string, kycDone bool) error {
	_, err := tx.Exec(ctx,
		`UPDATE clients SET status=$2,
		   retainer_ref     = CASE WHEN $3 <> '' THEN $3 ELSE retainer_ref END,
		   kyc_ref          = CASE WHEN $4 <> '' THEN $4 ELSE kyc_ref END,
		   kyc_completed_at = CASE WHEN $5 THEN now() ELSE kyc_completed_at END
		 WHERE id=$1`,
		id, toStatus, retainerRef, kycRef, kycDone)
	return err
}

// ConfirmConflictCheck stamps the manual conflict-check gate.
func ConfirmConflictCheck(ctx context.Context, tx pgx.Tx, id, byUser string) error {
	_, err := tx.Exec(ctx,
		"UPDATE clients SET conflict_check_at = now(), conflict_check_by = $2 WHERE id=$1", id, byUser)
	return err
}

func InsertStageEvent(ctx context.Context, tx pgx.Tx, e *StageEvent) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO client_stage_events (id, client_id, from_status, to_status, note, advanced_by)
		 VALUES ($1,$2,$3,$4,$5,$6)`,
		e.ID, e.ClientID, e.FromStatus, e.ToStatus, e.Note, e.AdvancedBy)
	return err
}

func ListStageEvents(ctx context.Context, tx pgx.Tx, clientID string) ([]StageEvent, error) {
	rows, err := tx.Query(ctx,
		`SELECT id, client_id, from_status, to_status, note, advanced_by, created_at
		 FROM client_stage_events WHERE client_id=$1 ORDER BY created_at`, clientID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []StageEvent{}
	for rows.Next() {
		var e StageEvent
		if err := rows.Scan(&e.ID, &e.ClientID, &e.FromStatus, &e.ToStatus, &e.Note, &e.AdvancedBy, &e.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

// CountFilesByClient counts files opened for a client (used to gate a
// client's advance to "active").
func CountFilesByClient(ctx context.Context, tx pgx.Tx, clientID string) (int, error) {
	var n int
	err := tx.QueryRow(ctx, "SELECT count(*) FROM files WHERE client_id = $1", clientID).Scan(&n)
	return n, err
}

func itoa(n int) string {
	if n < 10 {
		return string(rune('0' + n))
	}
	return string(rune('0'+n/10)) + string(rune('0'+n%10))
}
