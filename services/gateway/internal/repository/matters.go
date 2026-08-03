package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type Client struct {
	ID          string    `json:"id"`
	Name        string    `json:"name"`
	Email       string    `json:"email"`
	Phone       string    `json:"phone"`
	IDNumber    string    `json:"id_number"`
	KDPAConsent bool      `json:"kdpa_consent"`
	CreatedAt   time.Time `json:"created_at"`
}

type Matter struct {
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

type MatterEvent struct {
	ID        string    `json:"id"`
	MatterID  string    `json:"matter_id"`
	EventType string    `json:"event_type"`
	Note      string    `json:"note"`
	CreatedBy string    `json:"created_by"`
	CreatedAt time.Time `json:"created_at"`
}

type CourtDate struct {
	ID        string    `json:"id"`
	MatterID  string    `json:"matter_id"`
	Date      time.Time `json:"date"`
	Courtroom string    `json:"courtroom"`
	Judge     string    `json:"judge"`
	Purpose   string    `json:"purpose"`
	Reminded  bool      `json:"reminded"`
}

type Deadline struct {
	ID        string    `json:"id"`
	MatterID  string    `json:"matter_id"`
	Title     string    `json:"title"`
	DueAt     time.Time `json:"due_at"`
	RemindAt  time.Time `json:"remind_at"`
	Reminded  bool      `json:"reminded"`
	CreatedBy string    `json:"created_by"`
}

const matterCols = `m.id, m.reference, m.title, m.description, m.client_id, COALESCE(c.name,''),
	m.status, m.practice_area, m.court, m.court_case_number, m.assigned_to,
	m.opened_at, m.closed_at, m.created_by, m.created_at, m.updated_at`

func scanMatter(row pgx.Row) (*Matter, error) {
	var m Matter
	err := row.Scan(&m.ID, &m.Reference, &m.Title, &m.Description, &m.ClientID, &m.ClientName,
		&m.Status, &m.PracticeArea, &m.Court, &m.CourtCaseNumber, &m.AssignedTo,
		&m.OpenedAt, &m.ClosedAt, &m.CreatedBy, &m.CreatedAt, &m.UpdatedAt)
	if err != nil {
		return nil, err
	}
	return &m, nil
}

func ListMatters(ctx context.Context, tx pgx.Tx, status, search, clientID string) ([]Matter, error) {
	q := "SELECT " + matterCols + ` FROM matters m LEFT JOIN clients c ON c.id = m.client_id WHERE 1=1`
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
	var out []Matter
	for rows.Next() {
		var m Matter
		if err := rows.Scan(&m.ID, &m.Reference, &m.Title, &m.Description, &m.ClientID, &m.ClientName,
			&m.Status, &m.PracticeArea, &m.Court, &m.CourtCaseNumber, &m.AssignedTo,
			&m.OpenedAt, &m.ClosedAt, &m.CreatedBy, &m.CreatedAt, &m.UpdatedAt); err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

func MatterByID(ctx context.Context, tx pgx.Tx, id string) (*Matter, error) {
	return scanMatter(tx.QueryRow(ctx,
		"SELECT "+matterCols+" FROM matters m LEFT JOIN clients c ON c.id = m.client_id WHERE m.id = $1", id))
}

func InsertMatter(ctx context.Context, tx pgx.Tx, m *Matter) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO matters (id, reference, title, description, client_id, status, practice_area,
		   court, court_case_number, assigned_to, created_by)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
		m.ID, m.Reference, m.Title, m.Description, m.ClientID, m.Status, m.PracticeArea,
		m.Court, m.CourtCaseNumber, m.AssignedTo, m.CreatedBy)
	return err
}

func UpdateMatter(ctx context.Context, tx pgx.Tx, m *Matter) error {
	_, err := tx.Exec(ctx,
		`UPDATE matters SET title=$2, description=$3, client_id=$4, status=$5, practice_area=$6,
		   court=$7, court_case_number=$8, assigned_to=$9,
		   closed_at = CASE WHEN $5 = 'closed' AND closed_at IS NULL THEN now()
		                    WHEN $5 <> 'closed' THEN NULL ELSE closed_at END,
		   updated_at = now()
		 WHERE id=$1`,
		m.ID, m.Title, m.Description, m.ClientID, m.Status, m.PracticeArea,
		m.Court, m.CourtCaseNumber, m.AssignedTo)
	return err
}

func InsertMatterEvent(ctx context.Context, tx pgx.Tx, e *MatterEvent) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO matter_events (id, matter_id, event_type, note, created_by) VALUES ($1,$2,$3,$4,$5)",
		e.ID, e.MatterID, e.EventType, e.Note, e.CreatedBy)
	return err
}

func ListMatterEvents(ctx context.Context, tx pgx.Tx, matterID string) ([]MatterEvent, error) {
	rows, err := tx.Query(ctx,
		"SELECT id, matter_id, event_type, note, created_by, created_at FROM matter_events WHERE matter_id=$1 ORDER BY created_at DESC",
		matterID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []MatterEvent
	for rows.Next() {
		var e MatterEvent
		if err := rows.Scan(&e.ID, &e.MatterID, &e.EventType, &e.Note, &e.CreatedBy, &e.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, e)
	}
	return out, rows.Err()
}

func InsertCourtDate(ctx context.Context, tx pgx.Tx, cd *CourtDate) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO court_dates (id, matter_id, date, courtroom, judge, purpose) VALUES ($1,$2,$3,$4,$5,$6)",
		cd.ID, cd.MatterID, cd.Date, cd.Courtroom, cd.Judge, cd.Purpose)
	return err
}

func InsertDeadline(ctx context.Context, tx pgx.Tx, d *Deadline) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO deadlines (id, matter_id, title, due_at, remind_at, created_by) VALUES ($1,$2,$3,$4,$5,$6)",
		d.ID, d.MatterID, d.Title, d.DueAt, d.RemindAt, d.CreatedBy)
	return err
}

func ListUpcoming(ctx context.Context, tx pgx.Tx, within time.Duration) ([]CourtDate, []Deadline, error) {
	horizon := time.Now().Add(within)
	var cds []CourtDate
	rows, err := tx.Query(ctx,
		"SELECT id, matter_id, date, courtroom, judge, purpose, reminded FROM court_dates WHERE date BETWEEN now() AND $1 AND NOT reminded", horizon)
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var cd CourtDate
		if err := rows.Scan(&cd.ID, &cd.MatterID, &cd.Date, &cd.Courtroom, &cd.Judge, &cd.Purpose, &cd.Reminded); err != nil {
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
		"SELECT id, matter_id, title, due_at, remind_at, reminded, created_by FROM deadlines WHERE remind_at <= now() AND due_at > now() AND NOT reminded")
	if err != nil {
		return nil, nil, err
	}
	for rows.Next() {
		var d Deadline
		if err := rows.Scan(&d.ID, &d.MatterID, &d.Title, &d.DueAt, &d.RemindAt, &d.Reminded, &d.CreatedBy); err != nil {
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

func ListClients(ctx context.Context, tx pgx.Tx) ([]Client, error) {
	rows, err := tx.Query(ctx,
		"SELECT id, name, email, phone, id_number, kdpa_consent, created_at FROM clients ORDER BY name")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Client
	for rows.Next() {
		var c Client
		if err := rows.Scan(&c.ID, &c.Name, &c.Email, &c.Phone, &c.IDNumber, &c.KDPAConsent, &c.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

func ClientByID(ctx context.Context, tx pgx.Tx, id string) (*Client, error) {
	var c Client
	err := tx.QueryRow(ctx,
		"SELECT id, name, email, phone, id_number, kdpa_consent, created_at FROM clients WHERE id=$1", id).
		Scan(&c.ID, &c.Name, &c.Email, &c.Phone, &c.IDNumber, &c.KDPAConsent, &c.CreatedAt)
	if err != nil {
		return nil, err
	}
	return &c, nil
}

func InsertClient(ctx context.Context, tx pgx.Tx, c *Client) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO clients (id, name, email, phone, id_number, kdpa_consent) VALUES ($1,$2,$3,$4,$5,$6)",
		c.ID, c.Name, c.Email, c.Phone, c.IDNumber, c.KDPAConsent)
	return err
}

func itoa(n int) string {
	if n < 10 {
		return string(rune('0' + n))
	}
	return string(rune('0'+n/10)) + string(rune('0'+n%10))
}
