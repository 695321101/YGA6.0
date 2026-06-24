use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ── HTTP 请求/响应结构 ──

#[derive(Debug, Serialize, Deserialize)]
pub struct HttpResponse {
    pub status: u16,
    pub success: bool,
    pub headers: HashMap<String, String>,
    pub body: String,
    pub elapsed_ms: u64,
    pub error: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct EndpointCheckResult {
    pub endpoint: String,
    pub method: String,
    pub status: u16,
    pub success: bool,
    pub schema_match: bool,
    pub error: Option<String>,
    pub elapsed_ms: u64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct IntegrationTestResult {
    pub base_url: String,
    pub total: usize,
    pub passed: usize,
    pub failed: usize,
    pub results: Vec<EndpointCheckResult>,
}

// ── IPC 命令 ──

/// 发送 HTTP 请求
pub async fn tool_http_request(
    url: String,
    method: Option<String>,
    headers: Option<HashMap<String, String>>,
    body: Option<String>,
    timeout_ms: Option<u64>,
) -> Result<HttpResponse, String> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_millis(
            timeout_ms.unwrap_or(10000),
        ))
        .build()
        .map_err(|e| format!("创建 HTTP 客户端失败: {}", e))?;

    let method_str = method.unwrap_or_else(|| "GET".to_string());
    let req_method = match method_str.to_uppercase().as_str() {
        "GET" => reqwest::Method::GET,
        "POST" => reqwest::Method::POST,
        "PUT" => reqwest::Method::PUT,
        "DELETE" => reqwest::Method::DELETE,
        "PATCH" => reqwest::Method::PATCH,
        "HEAD" => reqwest::Method::HEAD,
        "OPTIONS" => reqwest::Method::OPTIONS,
        other => return Err(format!("不支持的 HTTP 方法: {}", other)),
    };

    let mut req = client.request(req_method, &url);

    if let Some(hdrs) = headers {
        for (k, v) in hdrs {
            req = req.header(&k, &v);
        }
    }

    if let Some(b) = body {
        req = req.header("Content-Type", "application/json");
        req = req.body(b);
    }

    let start = std::time::Instant::now();
    let resp = req.send().await;
    let elapsed_ms = start.elapsed().as_millis() as u64;

    match resp {
        Ok(r) => {
            let status = r.status().as_u16();
            let success = r.status().is_success();
            let mut resp_headers = HashMap::new();
            for (k, v) in r.headers() {
                if let Ok(val) = v.to_str() {
                    resp_headers.insert(k.to_string(), val.to_string());
                }
            }
            let body_text = r.text().await.unwrap_or_default();

            Ok(HttpResponse {
                status,
                success,
                headers: resp_headers,
                body: body_text,
                elapsed_ms,
                error: None,
            })
        }
        Err(e) => Ok(HttpResponse {
            status: 0,
            success: false,
            headers: HashMap::new(),
            body: String::new(),
            elapsed_ms,
            error: Some(e.to_string()),
        }),
    }
}

/// 批量检查 contracts.json 中的所有 endpoint
pub async fn tool_check_endpoints(
    base_url: String,
    contracts_path: String,
) -> Result<IntegrationTestResult, String> {
    let content = tokio::fs::read_to_string(&contracts_path)
        .await
        .map_err(|e| format!("contracts.json 读取失败: {}", e))?;

    let contracts: serde_json::Value =
        serde_json::from_str(&content).map_err(|e| format!("contracts.json 解析失败: {}", e))?;

    let endpoints = contracts
        .get("endpoints")
        .and_then(|e| e.as_array())
        .ok_or("contracts.json 缺少 endpoints 数组")?;

    let base = base_url.trim_end_matches('/');
    let mut results = Vec::new();

    for ep in endpoints {
        let method = ep.get("method").and_then(|m| m.as_str()).unwrap_or("GET");
        let path = ep.get("path").and_then(|p| p.as_str()).unwrap_or("/");
        let url = format!("{}{}", base, path);

        let start = std::time::Instant::now();
        let resp = tool_http_request(
            url.clone(),
            Some(method.to_string()),
            None,
            None,
            Some(5000),
        )
        .await;
        let elapsed_ms = start.elapsed().as_millis() as u64;

        match resp {
            Ok(r) => {
                let schema_match = if r.success {
                    check_response_schema(&r.body, ep.get("response"))
                } else {
                    false
                };

                results.push(EndpointCheckResult {
                    endpoint: format!("{} {}", method, path),
                    method: method.to_string(),
                    status: r.status,
                    success: r.success,
                    schema_match,
                    error: r.error,
                    elapsed_ms,
                });
            }
            Err(e) => {
                results.push(EndpointCheckResult {
                    endpoint: format!("{} {}", method, path),
                    method: method.to_string(),
                    status: 0,
                    success: false,
                    schema_match: false,
                    error: Some(e),
                    elapsed_ms,
                });
            }
        }
    }

    let total = results.len();
    let passed = results
        .iter()
        .filter(|r| r.success && r.schema_match)
        .count();
    let failed = total - passed;

    Ok(IntegrationTestResult {
        base_url: base.to_string(),
        total,
        passed,
        failed,
        results,
    })
}

/// 等待服务就绪（轮询 health endpoint）
pub async fn tool_wait_for_server(
    url: String,
    timeout_seconds: Option<u64>,
    interval_ms: Option<u64>,
) -> Result<bool, String> {
    let timeout = std::time::Duration::from_secs(timeout_seconds.unwrap_or(30));
    let interval = std::time::Duration::from_millis(interval_ms.unwrap_or(500));
    let start = std::time::Instant::now();

    loop {
        if start.elapsed() > timeout {
            return Ok(false);
        }

        match tool_http_request(url.clone(), Some("GET".to_string()), None, None, Some(2000)).await
        {
            Ok(r) if r.success => return Ok(true),
            _ => {}
        }

        tokio::time::sleep(interval).await;
    }
}

// ── 内部辅助 ──

fn check_response_schema(body: &str, expected_schema: Option<&serde_json::Value>) -> bool {
    let expected = match expected_schema {
        Some(s) => s,
        None => return true,
    };

    let actual: serde_json::Value = match serde_json::from_str(body) {
        Ok(v) => v,
        Err(_) => return false,
    };

    // simple check: expected schema fields exist in actual response
    if let Some(expected_obj) = expected.as_object() {
        if let Some(actual_obj) = actual.as_object() {
            for key in expected_obj.keys() {
                if !actual_obj.contains_key(key) {
                    return false;
                }
            }
            return true;
        }
        return false;
    }

    true
}
