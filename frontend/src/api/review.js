import request from "./request";
import { streamFromPost } from "../utils/sse";

// ── 阻塞 API（保留向后兼容）──────────────────────────────────────

export function submitReview(text) {
  return request.post("/review", { text });
}

export function submitQA(text) {
  return request.post("/qa", { text });
}

export function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  return request.post("/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
}

// ── 流式 API（SSE）─────────────────────────────────────────────────

/**
 * 流式合同审查 — 逐 token 返回审查报告。
 * @param {string} text 合同内容
 * @param {object} handlers { onEvent(event, data), onError(err), onComplete() }
 * @returns {AbortController} 用于中断流
 */
export function submitReviewStream(text, threadId, handlers) {
  return streamFromPost("/api/review/stream", { text, thread_id: threadId || null }, handlers);
}

/**
 * 流式法律咨询 — 逐 token 返回咨询结果。
 * @param {string} text 用户问题
 * @param {object} handlers { onEvent(event, data), onError(err), onComplete() }
 * @returns {AbortController} 用于中断流
 */
export function submitQAStream(text, threadId, handlers) {
  return streamFromPost("/api/qa/stream", { text, thread_id: threadId || null }, handlers);
}

/**
 * 流式文件上传审查。
 * @param {File} file 上传的合同文件
 * @param {object} handlers { onEvent(event, data), onError(err), onComplete() }
 * @returns {AbortController} 用于中断流
 */
export function uploadFileStream(file, threadId, handlers) {
  const controller = new AbortController();
  const { onEvent, onError, onComplete } = handlers;

  const token = localStorage.getItem("token");
  const formData = new FormData();
  formData.append("file", file);

  let url = "/api/upload/stream";
  if (threadId) {
    url += `?thread_id=${encodeURIComponent(threadId)}`;
  }

  fetch(url, {
    method: "POST",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: formData,
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
            } catch {}
          }
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
