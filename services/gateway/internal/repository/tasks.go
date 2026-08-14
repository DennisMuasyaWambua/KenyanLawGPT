package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type Task struct {
	ID             string     `json:"id"`
	MatterID       string     `json:"matter_id"`
	MatterRef      string     `json:"matter_ref,omitempty"`
	AssignedTo     *string    `json:"assigned_to,omitempty"`
	AssignedToName string     `json:"assigned_to_name,omitempty"`
	AssignedBy     string     `json:"assigned_by"`
	Title          string     `json:"title"`
	Description    string     `json:"description"`
	DueDate        *time.Time `json:"due_date,omitempty"`
	Status         string     `json:"status"`
	Priority       string     `json:"priority"`
	CreatedAt      time.Time  `json:"created_at"`
	CompletedAt    *time.Time `json:"completed_at,omitempty"`
}

const taskCols = `t.id, t.matter_id, COALESCE(m.reference,''), t.assigned_to, COALESCE(u.full_name,''),
	t.assigned_by, t.title, t.description, t.due_date, t.status, t.priority, t.created_at, t.completed_at`

func scanTask(row pgx.Row) (*Task, error) {
	var t Task
	if err := row.Scan(&t.ID, &t.MatterID, &t.MatterRef, &t.AssignedTo, &t.AssignedToName,
		&t.AssignedBy, &t.Title, &t.Description, &t.DueDate, &t.Status, &t.Priority,
		&t.CreatedAt, &t.CompletedAt); err != nil {
		return nil, err
	}
	return &t, nil
}

const taskFrom = ` FROM tasks t
	LEFT JOIN matters m ON m.id = t.matter_id
	LEFT JOIN users u   ON u.id = t.assigned_to`

func queryTasks(ctx context.Context, tx pgx.Tx, where string, args ...any) ([]Task, error) {
	rows, err := tx.Query(ctx, "SELECT "+taskCols+taskFrom+" "+where, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Task{}
	for rows.Next() {
		t, err := scanTask(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, *t)
	}
	return out, rows.Err()
}

// ListOwnTasks returns tasks assigned to userID.
func ListOwnTasks(ctx context.Context, tx pgx.Tx, userID string) ([]Task, error) {
	return queryTasks(ctx, tx, "WHERE t.assigned_to = $1 ORDER BY t.status='done', t.due_date NULLS LAST, t.created_at DESC", userID)
}

// ListAllTasks returns every task in the firm.
func ListAllTasks(ctx context.Context, tx pgx.Tx) ([]Task, error) {
	return queryTasks(ctx, tx, "ORDER BY t.status='done', t.due_date NULLS LAST, t.created_at DESC")
}

// ListTasksByMatter returns all tasks for one matter.
func ListTasksByMatter(ctx context.Context, tx pgx.Tx, matterID string) ([]Task, error) {
	return queryTasks(ctx, tx, "WHERE t.matter_id = $1 ORDER BY t.status='done', t.due_date NULLS LAST, t.created_at DESC", matterID)
}

func GetTask(ctx context.Context, tx pgx.Tx, id string) (*Task, error) {
	return scanTask(tx.QueryRow(ctx, "SELECT "+taskCols+taskFrom+" WHERE t.id = $1", id))
}

func InsertTask(ctx context.Context, tx pgx.Tx, t *Task) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO tasks (id, matter_id, assigned_to, assigned_by, title, description, due_date, status, priority)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		t.ID, t.MatterID, t.AssignedTo, t.AssignedBy, t.Title, t.Description, t.DueDate, t.Status, t.Priority)
	return err
}

// UpdateTaskFull edits all mutable fields (task managers).
func UpdateTaskFull(ctx context.Context, tx pgx.Tx, t *Task) error {
	_, err := tx.Exec(ctx,
		`UPDATE tasks SET assigned_to=$2, title=$3, description=$4, due_date=$5, status=$6, priority=$7,
		   completed_at = CASE WHEN $6='done' AND completed_at IS NULL THEN now()
		                       WHEN $6<>'done' THEN NULL ELSE completed_at END
		 WHERE id=$1`,
		t.ID, t.AssignedTo, t.Title, t.Description, t.DueDate, t.Status, t.Priority)
	return err
}

// UpdateTaskStatus lets an assignee move their own task's status without full
// edit rights.
func UpdateTaskStatus(ctx context.Context, tx pgx.Tx, id, status string) error {
	_, err := tx.Exec(ctx,
		`UPDATE tasks SET status=$2,
		   completed_at = CASE WHEN $2='done' AND completed_at IS NULL THEN now()
		                       WHEN $2<>'done' THEN NULL ELSE completed_at END
		 WHERE id=$1`, id, status)
	return err
}

func DeleteTask(ctx context.Context, tx pgx.Tx, id string) error {
	_, err := tx.Exec(ctx, "DELETE FROM tasks WHERE id=$1", id)
	return err
}

// CaseStatus is one row of the case-status dashboard.
type CaseStatus struct {
	MatterID     string    `json:"matter_id"`
	Reference    string    `json:"reference"`
	Title        string    `json:"title"`
	ClientName   string    `json:"client_name"`
	Status       string    `json:"status"`
	OpenTasks    int       `json:"open_tasks"`
	OverdueTasks int       `json:"overdue_tasks"`
	LastActivity time.Time `json:"last_activity"`
}

// CaseDashboard aggregates, per matter, open/overdue task counts and last
// activity alongside the matter status.
func CaseDashboard(ctx context.Context, tx pgx.Tx) ([]CaseStatus, error) {
	rows, err := tx.Query(ctx, `
		SELECT m.id, m.reference, m.title, COALESCE(c.name,''), m.status,
		       COALESCE(t.open_count,0), COALESCE(t.overdue_count,0),
		       GREATEST(m.updated_at, COALESCE(t.last_task, m.updated_at)) AS last_activity
		FROM matters m
		LEFT JOIN clients c ON c.id = m.client_id
		LEFT JOIN (
			SELECT matter_id,
			       count(*) FILTER (WHERE status <> 'done') AS open_count,
			       count(*) FILTER (WHERE status <> 'done' AND due_date IS NOT NULL AND due_date < now()) AS overdue_count,
			       max(created_at) AS last_task
			FROM tasks GROUP BY matter_id
		) t ON t.matter_id = m.id
		ORDER BY (m.status = 'closed'), last_activity DESC`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []CaseStatus{}
	for rows.Next() {
		var cs CaseStatus
		if err := rows.Scan(&cs.MatterID, &cs.Reference, &cs.Title, &cs.ClientName, &cs.Status,
			&cs.OpenTasks, &cs.OverdueTasks, &cs.LastActivity); err != nil {
			return nil, err
		}
		out = append(out, cs)
	}
	return out, rows.Err()
}
