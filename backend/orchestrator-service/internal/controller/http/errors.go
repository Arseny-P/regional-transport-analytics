package httpcontroller

import (
	"errors"
	"net/http"
	"orchestrator-service/internal/domain"
	httpdto "orchestrator-service/internal/dto/http"
)

var (
	errMissingJobID    = errors.New("missing job_id")
	errInvalidJobID    = errors.New("invalid job_id")
	errInvalidJSON     = errors.New("invalid JSON")
	errInvalidRegionID = errors.New("invalid region_id")
)

func (hc *HTTPController) writeError(w http.ResponseWriter, err error) {
	status, body := ReturnErrorRespWithCode(err)
	hc.WriteResponse(w, status, body)
}

func ReturnErrorRespWithCode(err error) (int, httpdto.Error) {
	switch {
	case errors.Is(err, errMissingJobID):
		return http.StatusBadRequest, httpdto.Error{
			Code: "missing_job_id", Field: "job_id",
			Message: "Укажи job_id в параметрах запроса",
		}
	case errors.Is(err, errInvalidJobID):
		return http.StatusUnprocessableEntity, httpdto.Error{
			Code: "invalid_job_id", Field: "job_id",
			Message: "job_id должен быть UUID",
		}
	case errors.Is(err, errInvalidJSON):
		return http.StatusBadRequest, httpdto.Error{
			Code:    "invalid_json",
			Message: "Тело запроса должно содержать корректный JSON-объект",
		}
	case errors.Is(err, errInvalidRegionID):
		return http.StatusUnprocessableEntity, httpdto.Error{
			Code: "invalid_region_id", Field: "region_id",
			Message: "region_id должен быть UUID",
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
	case errors.Is(err, domain.ErrJobConflict):
		return http.StatusConflict, httpdto.Conflict{
			Code:    "job_parameters_conflict",
			Field:   "job_id",
			Message: "Этот job_id уже используется для анализа с другими параметрами",
		}
	case errors.Is(err, domain.ErrInternalDB):
		return http.StatusInternalServerError, httpdto.InternalError{
			Code:    "internal_db_error",
			Message: "Не удалось выполнить операцию с базой данных",
		}
	case errors.Is(err, domain.ErrInternalServer):
		return http.StatusInternalServerError, httpdto.InternalError{
			Code:    "internal_error",
			Message: "Внутренняя ошибка сервера",
		}
	}

	return http.StatusInternalServerError, httpdto.Error{
		Code: "internal_error", Message: "Внутренняя ошибка сервера",
	}
}
