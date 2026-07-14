# ── Cloudflare R2 — public forecast feed (catch.unagieel.net) ────────────────
#
# Zero-egress static JSON delivery. The scheduler Lambda uploads ~10 small
# files per run via R2's S3-compatible API; readers are served through the
# Cloudflare CDN with free egress, so bot traffic can never generate cost or
# touch Supabase (lesson from the 2026-06 egress incident).
#
# One-time manual prerequisites (Cloudflare dashboard):
#   1. Enable R2 on the account
#   2. Create an API token for Terraform: "Workers R2 Storage: Edit" +
#      "Zone > DNS: Edit" (unagieel.net)  → cloudflare_api_token
#   3. Create an R2 API token (S3 credentials) for the Lambda uploader
#      → r2_access_key_id / r2_secret_access_key

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

resource "cloudflare_r2_bucket" "catch" {
  account_id = var.cloudflare_account_id
  name       = "unagi-catch"
  location   = "WEUR" # Western Europe — closest to Swedish readers
}

resource "cloudflare_r2_custom_domain" "catch" {
  account_id  = var.cloudflare_account_id
  bucket_name = cloudflare_r2_bucket.catch.name
  domain      = "catch.unagieel.net"
  zone_id     = var.cloudflare_zone_id
  enabled     = true
  min_tls     = "1.2"
}

resource "cloudflare_r2_bucket_cors" "catch" {
  account_id  = var.cloudflare_account_id
  bucket_name = cloudflare_r2_bucket.catch.name
  rules = [{
    id = "public-read"
    allowed = {
      methods = ["GET", "HEAD"]
      origins = ["*"]
    }
    max_age_seconds = 86400
  }]
}
