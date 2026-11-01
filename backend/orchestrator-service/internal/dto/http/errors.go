package httpdto

type Error struct {
	Code string `json:"code"`

	Field string `json:"field,omitempty"`

	Message string `json:"message"`
}

type BadRequest = Error

type Conflict = Error

type InternalError = Error

type NotFound Error

type ValidationError = Error
