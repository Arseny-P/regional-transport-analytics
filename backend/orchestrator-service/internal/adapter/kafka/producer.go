package kafkaproducer

import (
	"context"
	"encoding/json"
	"orchestrator-service/internal/domain"
	kafkadto "orchestrator-service/internal/dto/kafka"

	"github.com/segmentio/kafka-go"
)

type Producer struct {
	writer *kafka.Writer
}

func NewProducer(address string) *Producer {
	return &Producer{
		writer: &kafka.Writer{
			Addr:                   kafka.TCP(address),
			Balancer:               &kafka.Hash{},
			RequiredAcks:           kafka.RequireAll,
			AllowAutoTopicCreation: true,
		},
	}
}

func (p *Producer) WriteOutboxMessage(ctx context.Context, message *domain.OutboxMessage) error {

	envelope := kafkadto.OutboxMessage{
		MessageID: message.ID,
		JobID:     message.JobID,
		Type:      message.CommandType,
	}
	switch message.CommandType {
	case "START":
		transports := make([]string, len(message.TransportTypes))
		for i, transport := range message.TransportTypes {
			transports[i] = string(transport)
		}
		envelope.Payload = kafkadto.CommandPayload{
			Area: &kafkadto.Area{
				FirstPoint: kafkadto.MapPoint{
					Latitude: message.Point1.Latitude, Longitude: message.Point1.Longitude,
				},
				SecondPoint: kafkadto.MapPoint{
					Latitude: message.Point2.Latitude, Longitude: message.Point2.Longitude,
				},
			},
			Transports: transports,
		}
	case "CANCEL":
	default:
		return domain.ErrInternalServer
	}

	messageValue, err := json.Marshal(envelope)
	if err != nil {
		return domain.ErrInternalServer
	}
	return p.writer.WriteMessages(ctx, kafka.Message{
		Topic: "analysis.commands",
		Key:   []byte(message.JobID.String()),
		Value: messageValue,
	})

}

func (p *Producer) WriteDLQMessage(ctx context.Context, message *domain.DLQMessage) error {
	dtoMessage := kafkadto.DLQMessage{
		JobID:     message.JobID,
		Key:       message.Key,
		Topic:     message.Topic,
		Partition: message.Partition,
		Offset:    message.Offset,
		Payload:   message.Payload,
		Error:     message.Error,
	}
	messageValue, err := json.Marshal(dtoMessage)
	if err != nil {
		return domain.ErrInternalServer
	}

	return p.writer.WriteMessages(ctx, kafka.Message{
		Topic: "analysis.results.dlq",
		Key:   message.Key,
		Value: messageValue,
	})
}

func (p *Producer) Close() error {
	return p.writer.Close()
}
