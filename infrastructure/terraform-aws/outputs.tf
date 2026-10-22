output "frontend_bucket" { value = aws_s3_bucket.frontend.id }
output "cloudfront_distribution_id" { value = aws_cloudfront_distribution.frontend.id }
output "site_url" { value = "https://${aws_cloudfront_distribution.frontend.domain_name}" }
output "api_url" { value = "${aws_apigatewayv2_api.energy.api_endpoint}/api/energy" }
output "deployment_resource_ids" {
  value = {
    api_id                     = aws_apigatewayv2_api.energy.id
    cloudfront_distribution_id = aws_cloudfront_distribution.frontend.id
    cloudfront_oac_id          = aws_cloudfront_origin_access_control.frontend.id
  }
}
