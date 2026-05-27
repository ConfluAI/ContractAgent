import request from "./request";

export function getHistory() {
  return request.get("/history");
}

export function deleteHistory(id) {
  return request.delete(`/history/${id}`);
}
