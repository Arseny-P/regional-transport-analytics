package kafkacontroller

import (
	"context"
	"encoding/json"
	"fmt"
	"orchestrator-service/internal/domain"
	kafkadto "orchestrator-service/internal/dto/kafka"

	"github.com/google/uuid"
	"github.com/segmentio/kafka-go"
)

type Consumer struct {
	reader *kafka.Reader
}

func NewConsumer(address string) *Consumer {
	return &Consumer{
		reader: kafka.NewReader(kafka.ReaderConfig{
			Brokers: []string{address},
			GroupID: "analysis1",
			Topic:   "analysis.results",
		}),
	}
}

func (c *Consumer) FetchMessage(ctx context.Context) (domain.InboxMessage, kafka.Message, error) {
	kafkaMessage, err := c.reader.FetchMessage(ctx)
	if err != nil {
		return domain.InboxMessage{}, kafka.Message{}, err
	}
	var dtoInboxMessage kafkadto.InboxMessage
	err = json.Unmarshal(kafkaMessage.Value, &dtoInboxMessage)
	if err != nil {
		return domain.InboxMessage{}, kafkaMessage, fmt.Errorf("decode analysis message: %w: %w", domain.ErrInvalidKafkaMessage, err)
	}
	if validateErr := validateInboxMessage(&dtoInboxMessage); validateErr != nil {
		return domain.InboxMessage{}, kafkaMessage, validateErr
	}

	inboxMessage := domain.InboxMessage{
		MessageID: dtoInboxMessage.MessageID,
		JobID:     dtoInboxMessage.JobID,
		Type:      dtoInboxMessage.Type,
		Payload: domain.AnalysisPayload{
			Status: domain.JobStatus(dtoInboxMessage.Payload.Status),
		},
	}
	if dtoInboxMessage.Payload.Metrics != nil {
		inboxMessage.Payload.Metrics = make([]domain.Metric, 0, len(dtoInboxMessage.Payload.Metrics))
	}
	for _, metric := range dtoInboxMessage.Payload.Metrics {
		inboxMessage.Payload.Metrics = append(inboxMessage.Payload.Metrics, domain.Metric{
			Name:  metric.Name,
			Value: metric.Value,
		})
	}

	if dtoInboxMessage.Payload.Graph != nil {
		graph := dtoInboxMessage.Payload.Graph
		nodes := make([]domain.GraphNode, 0, len(graph.Nodes))
		edges := make([]domain.GraphEdge, 0, len(graph.Edges))
		for _, node := range graph.Nodes {
			nodes = append(nodes, domain.GraphNode{
				ID:         node.ID,
				Position:   node.Position,
				Attributes: node.Attributes,
			})
		}

		for _, edge := range graph.Edges {
			edges = append(edges, domain.GraphEdge{
				ID:         edge.ID,
				Source:     edge.Source,
				Target:     edge.Target,
				Geometry:   edge.Geometry,
				Attributes: edge.Attributes,
			})
		}
		inboxMessage.Payload.Graph = &domain.Graph{Nodes: nodes, Edges: edges}
	}
	if dtoInboxMessage.Payload.Error != nil {
		inboxMessage.Payload.Error = &domain.ErrorResp{
			Code:    dtoInboxMessage.Payload.Error.Code,
			Message: dtoInboxMessage.Payload.Error.Message,
		}
	}
	return inboxMessage, kafkaMessage, nil
}

func validateInboxMessage(message *kafkadto.InboxMessage) error {
	if message.MessageID == uuid.Nil || message.JobID == uuid.Nil {
		return fmt.Errorf("%w: message_id and job_id must be nonzero UUIDs", domain.ErrInvalidKafkaMessage)
	}
	switch message.Type {
	case "STATUS", "RESULT":
	default:
		return fmt.Errorf("%w: unsupported event type %q", domain.ErrInvalidKafkaMessage, message.Type)
	}
	switch message.Payload.Status {
	case "queued", "running", "completed", "failed", "cancel_requested", "canceled":
	default:
		return fmt.Errorf("%w: unsupported job status %q", domain.ErrInvalidKafkaMessage, message.Payload.Status)
	}
	return nil
}

func (c *Consumer) CommitMessage(ctx context.Context, message *kafka.Message) error {
	return c.reader.CommitMessages(ctx, *message)
}

func (c *Consumer) Close() error {
	return c.reader.Close()
}
