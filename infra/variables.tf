variable "aws_region" {
  description = "AWS region"
  default     = "eu-north-1"
}

variable "project" {
  description = "Project name prefix for all resources"
  default     = "unagi"
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

variable "api_key" {
  description = "API key for X-Unagi-Key header authentication"
  sensitive   = true
}

# ── Cloudflare (R2 public forecast feed — catch.unagieel.net) ────────────────

variable "cloudflare_api_token" {
  description = "Cloudflare API token for Terraform (Workers R2 Storage: Edit + Zone DNS: Edit on unagieel.net)"
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account ID (dashboard sidebar)"
}

variable "cloudflare_zone_id" {
  description = "Zone ID for unagieel.net"
}

variable "r2_access_key_id" {
  description = "R2 API token access key (S3-compatible credentials for the Lambda uploader)"
  sensitive   = true
}

variable "r2_secret_access_key" {
  description = "R2 API token secret key"
  sensitive   = true
}
