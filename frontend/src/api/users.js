import request from "./request";

export function getUsers() {
  return request.get("/users");
}

export function deleteUser(id) {
  return request.delete(`/users/${id}`);
}

export function updateRole(id, role) {
  return request.put(`/users/${id}/role`, { role });
}
