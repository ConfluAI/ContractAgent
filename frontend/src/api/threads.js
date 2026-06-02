import request from "./request";

export function listThreads() {
  return request.get("/threads");
}

export function getThread(id) {
  return request.get(`/threads/${id}`);
}

export function getMessages(id) {
  return request.get(`/threads/${id}/messages`);
}

export function deleteThread(id) {
  return request.delete(`/threads/${id}`);
}
