import request from "./request";

export function login(username, password) {
  const formData = new URLSearchParams();
  formData.append("username", username);
  formData.append("password", password);
  return request.post("/auth/login", formData, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
}

export function register(username, password, role = "user") {
  return request.post("/auth/register", { username, password, role });
}

export function getMe() {
  return request.get("/auth/me");
}
