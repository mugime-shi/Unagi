output "api_url" {
  description = "Public API Gateway URL"
  value       = aws_apigatewayv2_api.main.api_endpoint
}

output "ecr_api_url" {
  description = "ECR repository URL for the API image"
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_scheduler_url" {
  description = "ECR repository URL for the scheduler image"
  value       = aws_ecr_repository.scheduler.repository_url
}
