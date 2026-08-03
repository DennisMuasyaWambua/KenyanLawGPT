package repository

import (
	"context"
	"time"

	"github.com/jackc/pgx/v5"
)

type Message struct {
	ID          string    `json:"id"`
	MatterID    *string   `json:"matter_id"`
	ClientID    *string   `json:"client_id"`
	Channel     string    `json:"channel"`   // sms|email|whatsapp|inapp
	Direction   string    `json:"direction"` // outbound|inbound
	ToAddr      string    `json:"to_addr"`
	FromAddr    string    `json:"from_addr"`
	Body        string    `json:"body"`
	Status      string    `json:"status"` // queued|sent|delivered|failed|received
	ProviderRef string    `json:"provider_ref"`
	CreatedAt   time.Time `json:"created_at"`
}

const msgCols = "id, matter_id, client_id, channel, direction, to_addr, from_addr, body, status, COALESCE(provider_ref,''), created_at"

func InsertMessage(ctx context.Context, tx pgx.Tx, m *Message) error {
	_, err := tx.Exec(ctx,
		`INSERT INTO messages (id, matter_id, client_id, channel, direction, to_addr, from_addr, body, status, provider_ref)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
		m.ID, m.MatterID, m.ClientID, m.Channel, m.Direction, m.ToAddr, m.FromAddr, m.Body, m.Status, m.ProviderRef)
	return err
}

func ListMessages(ctx context.Context, tx pgx.Tx, clientID, channel string) ([]Message, error) {
	q := "SELECT " + msgCols + " FROM messages WHERE 1=1"
	args := []any{}
	if clientID != "" {
		args = append(args, clientID)
		q += " AND client_id = $1"
	}
	if channel != "" {
		args = append(args, channel)
		q += " AND channel = $" + itoa(len(args))
	}
	q += " ORDER BY created_at DESC LIMIT 200"
	rows, err := tx.Query(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Message
	for rows.Next() {
		var m Message
		if err := rows.Scan(&m.ID, &m.MatterID, &m.ClientID, &m.Channel, &m.Direction, &m.ToAddr, &m.FromAddr, &m.Body, &m.Status, &m.ProviderRef, &m.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

// UpdateMessageStatusByRef is used by delivery-status webhooks.
func UpdateMessageStatusByRef(ctx context.Context, tx pgx.Tx, providerRef, status string) (bool, error) {
	tag, err := tx.Exec(ctx, "UPDATE messages SET status=$2 WHERE provider_ref=$1", providerRef, status)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() > 0, nil
}

type Notification struct {
	ID        string    `json:"id"`
	UserID    string    `json:"user_id"`
	Kind      string    `json:"kind"`
	Body      string    `json:"body"`
	Read      bool      `json:"read"`
	CreatedAt time.Time `json:"created_at"`
}

func InsertNotification(ctx context.Context, tx pgx.Tx, n *Notification) error {
	_, err := tx.Exec(ctx,
		"INSERT INTO notifications (id, user_id, kind, body) VALUES ($1,$2,$3,$4)",
		n.ID, n.UserID, n.Kind, n.Body)
	return err
}

func ListNotifications(ctx context.Context, tx pgx.Tx, userID string) ([]Notification, error) {
	rows, err := tx.Query(ctx,
		"SELECT id, user_id, kind, body, read, created_at FROM notifications WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50",
		userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Notification
	for rows.Next() {
		var n Notification
		if err := rows.Scan(&n.ID, &n.UserID, &n.Kind, &n.Body, &n.Read, &n.CreatedAt); err != nil {
			return nil, err
		}
		out = append(out, n)
	}
	return out, rows.Err()
}
