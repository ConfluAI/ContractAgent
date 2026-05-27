import { ref } from "vue";
import { defineStore } from "pinia";
import { login as apiLogin, register as apiRegister, getMe } from "../api/auth";
import router from "../router";

export const useAuthStore = defineStore("auth", () => {
  const token = ref(localStorage.getItem("token") || "");
  const user = ref(null);
  const initialized = ref(false);

  async function login(username, password) {
    const { data } = await apiLogin(username, password);
    token.value = data.access_token;
    localStorage.setItem("token", data.access_token);
    await fetchUser();
    initialized.value = true;
    if (user.value?.role === "admin") {
      router.push("/admin/dashboard");
    } else {
      router.push("/user/dashboard");
    }
  }

  async function register(username, password, role = "user") {
    await apiRegister(username, password, role);
  }

  async function fetchUser() {
    try {
      const { data } = await getMe();
      user.value = data;
    } catch {
      token.value = "";
      user.value = null;
      localStorage.removeItem("token");
    }
  }

  async function init() {
    if (initialized.value) return;
    if (token.value) {
      await fetchUser();
    }
    initialized.value = true;
  }

  function logout() {
    token.value = "";
    user.value = null;
    localStorage.removeItem("token");
    router.push("/login");
  }

  return { token, user, initialized, login, register, fetchUser, init, logout };
});
