import request from "./request";

export function submitReview(text) {
  return request.post("/review", { text });
}

export function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  return request.post("/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
}
