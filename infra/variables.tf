variable "aws_region" {
  description = "AWS region"
  default     = "eu-north-1"
}

variable "project" {
  description = "Project name prefix for all resources"
  default     = "namazu"
}

variable "database_url" {
  description = "PostgreSQL connection string (Supabase)"
  sensitive   = true
}

variable "entsoe_api_key" {
  description = "ENTSO-E API key for electricity spot prices"
  sensitive   = true
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  default     = "latest"
}

variable "vapid_private_key" {
  description = "VAPID private key for Web Push notifications (base64url)"
  sensitive   = true
  default     = ""
}

variable "vapid_public_key" {
  description = "VAPID public key for Web Push notifications (base64url)"
  default     = ""
}

variable "vapid_contact" {
  description = "VAPID contact email (mailto:...)"
  default     = ""
}

variable "telegram_bot_token" {
  description = "Telegram Bot API token"
  sensitive   = true
  default     = ""
}

variable "telegram_chat_id" {
  description = "Telegram chat ID for price alert recipient"
  sensitive   = true
  default     = ""
}
