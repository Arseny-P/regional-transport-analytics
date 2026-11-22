package httpcontroller

import (
	"errors"
	"net/http"
	"orchestrator-service/internal/domain"
	httpdto "orchestrator-service/internal/dto/http"
)

var (
	errMissingJobID         = errors.New("missing job_id")
	errInvalidJobID         = errors.New("invalid job_id")
	errInvalidJSON          = errors.New("invalid JSON")
	errInvalidRegionID      = errors.New("invalid region_id")
	errInvalidRegionPathID  = errors.New("invalid region_id in path")
	errEntityTooLarge       = errors.New("entity too large")
	errMissingFile          = errors.New("missing file")
	errInvalidMultipart     = errors.New("invalid multipart form")
	errUnsupportedMediaType = errors.New("unsupported media type")
)

func (hc *HTTPController) writeError(w http.ResponseWriter, err error) {
	status, body := ReturnErrorRespWithCode(err)
	hc.WriteResponse(w, status, body)
}

func ReturnErrorRespWithCode(err error) (int, httpdto.Error) {
	switch {
	case errors.Is(err, errEntityTooLarge):
		return http.StatusRequestEntityTooLarge, httpdto.Error{
			Code: "file_too_large", Field: "file", Message: "Размер файла не должен превышать 20 000 000 байт",
		}
	case errors.Is(err, errMissingFile):
		return http.StatusBadRequest, httpdto.Error{
			Code: "missing_file", Field: "file", Message: "Передай файл в поле file",
		}
	case errors.Is(err, errInvalidMultipart):
		return http.StatusBadRequest, httpdto.Error{
			Code: "invalid_multipart", Field: "file", Message: "Передай ровно один файл в multipart/form-data",
		}
	case errors.Is(err, errUnsupportedMediaType):
		return http.StatusUnsupportedMediaType, httpdto.Error{
			Code: "unsupported_media_type", Message: "Ожидается multipart/form-data",
		}
	case errors.Is(err, errMissingJobID):
		return http.StatusBadRequest, httpdto.Error{
			Code: "missing_job_id", Field: "job_id",
			Message: "Укажи job_id в параметрах запроса",
		}
	case errors.Is(err, errInvalidJobID):
		return http.StatusBadRequest, httpdto.Error{
			Code: "invalid_job_id", Field: "job_id",
			Message: "job_id должен быть UUID",
		}
	case errors.Is(err, errInvalidJSON):
		return http.StatusBadRequest, httpdto.Error{
			Code:    "invalid_json",
			Message: "Тело запроса должно содержать корректный JSON-объект",
		}
	case errors.Is(err, errInvalidRegionPathID):
		return http.StatusBadRequest, httpdto.Error{
			Code: "invalid_region_id", Field: "region_id",
			Message: "region_id должен быть UUID",
		}
	case errors.Is(err, errInvalidRegionID):
		return http.StatusUnprocessableEntity, httpdto.Error{
			Code: "invalid_region_id", Field: "region_id",
			Message: "region_id должен быть UUID",
		}
	}

	return returnDomainErrorRespWithCode(err)
}

func returnDomainErrorRespWithCode(err error) (int, httpdto.Error) {
	switch {
	case errors.Is(err, domain.ErrInvalidRegionFile):
		return http.StatusUnprocessableEntity, httpdto.Error{
			Code: "invalid_region_file", Field: "file",
			Message: "Файл должен содержать непустую FeatureCollection с корректными границами Polygon или MultiPolygon",
		}
	case errors.Is(err, domain.ErrInvalidCoordinates):
		return http.StatusUnprocessableEntity, httpdto.Error{
			Code: "invalid_coordinates", Field: "area",
			Message: "Широта должна быть от -90 до 90, долгота — от -180 до 180",
		}
	case errors.Is(err, domain.ErrInvalidArea):
		return http.StatusUnprocessableEntity, httpdto.Error{
			Code: "invalid_area", Field: "area",
			Message: "Широты и долготы двух точек должны различаться: площадь области не может быть нулевой",
		}
	case errors.Is(err, domain.ErrAreaOutOfBounds):
		return http.StatusUnprocessableEntity, httpdto.Error{
			Code: "area_outside_region", Field: "area",
			Message: "Выбранная область выходит за границы региона",
		}
	case errors.Is(err, domain.ErrInvalidTransports):
		return http.StatusUnprocessableEntity, httpdto.Error{
			Code: "invalid_transports", Field: "transports",
			Message: "Укажи хотя бы один вид транспорта: road, rail или sea",
		}
	case errors.Is(err, domain.ErrRegionNotFound):
		return http.StatusNotFound, httpdto.Error{
			Code:    "region_not_found",
			Field:   "region_id",
			Message: "Регион не найден",
		}
	case errors.Is(err, domain.ErrInternalStorage), errors.Is(err, domain.ErrInvalidRegionData):
		return http.StatusInternalServerError, httpdto.InternalError{
			Code:    "storage_error",
			Message: "Не удалось прочитать данные региона",
		}
	case errors.Is(err, domain.ErrJobAlreadyFinished):
		return http.StatusConflict, httpdto.Conflict{
			Code: "job_already_finished", Field: "job_id",
			Message: "Завершённую задачу нельзя отменить",
		}

	case errors.Is(err, domain.ErrHeartbeatTimeoutExceeded):
		return http.StatusOK, httpdto.Error{
			Code:    "heartbeat_timeout_exceeded",
			Message: "Heartbeat не поступал более 10 секунд. Срок подтверждения активности истёк",
		}
	case errors.Is(err, domain.ErrJobConflict):
		return http.StatusConflict, httpdto.Conflict{
			Code:    "job_parameters_conflict",
			Field:   "job_id",
			Message: "Этот job_id уже используется для анализа с другими параметрами",
		}
	case errors.Is(err, domain.ErrJobNotFound):
		return http.StatusNotFound, httpdto.Error{
			Code: "job_not_found", Field: "job_id",
			Message: "Задача не найдена",
		}
	case errors.Is(err, domain.ErrInternalDB):
		return http.StatusInternalServerError, httpdto.InternalError{
			Code:    "internal_db_error",
			Message: "Не удалось выполнить операцию с базой данных",
		}
	}

	return http.StatusInternalServerError, httpdto.Error{
		Code: "internal_error", Message: "Внутренняя ошибка сервера",
	}
}
