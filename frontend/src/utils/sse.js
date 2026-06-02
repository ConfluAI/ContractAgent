/**
 * POST SSE 客户端 — 用 fetch + ReadableStream 解析 SSE 协议。
 *
 * EventSource 只支持 GET，所以我们需要自己实现 POST SSE。
 *
 * 用法:
 *   const ctrl = streamFromPost("/review/stream", { text: "..." }, {
 *     onEvent(event, data) { ... },
 *     onError(err) { ... },
 *     onComplete() { ... },
 *   });
 *   // 需要中断时: ctrl.abort()
 */

export function streamFromPost(url, body, handlers) {
  const controller = new AbortController();
  const { onEvent, onError, onComplete } = handlers;

  const token = localStorage.getItem("token");
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };

  fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const errText = await response.text().catch(() => "");
        let detail = errText;
        try {
          const parsed = JSON.parse(errText);
          detail = parsed.detail || errText;
        } catch {}
        if (onError) onError(new Error(detail || `HTTP ${response.status}`));
        if (onComplete) onComplete();
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n");
        buffer = parts.pop() || "";

        for (const line of parts) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              if (onEvent) onEvent(currentEvent, data);
            } catch {
              // 忽略解析失败的行
            }
          }
          // 空行 = 事件分隔符，重置
          if (line === "") {
            currentEvent = "";
          }
        }
      }

      if (onComplete) onComplete();
    })
    .catch((err) => {
      if (err.name !== "AbortError" && onError) {
        onError(err);
      }
      if (onComplete) onComplete();
    });

  return controller;
}
