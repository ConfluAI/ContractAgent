import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "../stores/auth";

const routes = [
  {
    path: "/login",
    component: () => import("../views/Login.vue"),
    meta: { guest: true },
  },
  {
    path: "/register",
    component: () => import("../views/Register.vue"),
    meta: { guest: true },
  },
  {
    path: "/admin",
    component: () => import("../layouts/DashboardLayout.vue"),
    meta: { requiresAuth: true, role: "admin" },
    children: [
      { path: "", redirect: "/admin/dashboard" },
      { path: "dashboard", component: () => import("../views/admin/Dashboard.vue"), meta: { title: "管理首页" } },
      { path: "users", component: () => import("../views/admin/UserManagement.vue"), meta: { title: "用户管理" } },
      { path: "review", component: () => import("../components/ContractReviewPage.vue"), meta: { title: "合同审查" } },
      { path: "history", component: () => import("../components/QueryHistoryPage.vue"), meta: { title: "查询历史" } },
    ],
  },
  {
    path: "/user",
    component: () => import("../layouts/DashboardLayout.vue"),
    meta: { requiresAuth: true, role: "user" },
    children: [
      { path: "", redirect: "/user/dashboard" },
      { path: "dashboard", component: () => import("../views/admin/Dashboard.vue"), meta: { title: "个人信息" } },
      { path: "review", component: () => import("../components/ContractReviewPage.vue"), meta: { title: "合同审查" } },
      { path: "history", component: () => import("../components/QueryHistoryPage.vue"), meta: { title: "查询历史" } },
    ],
  },
  { path: "/", redirect: "/login" },
  { path: "/:pathMatch(.*)*", redirect: "/login" },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore();

  if (!authStore.initialized && authStore.token) {
    await authStore.init();
  }

  if (to.meta.requiresAuth && !authStore.token) {
    return next("/login");
  }

  if (to.meta.role && authStore.user && authStore.user.role !== to.meta.role) {
    return next(authStore.user.role === "admin" ? "/admin" : "/user");
  }

  if (to.meta.guest && authStore.token && authStore.user) {
    return next(authStore.user.role === "admin" ? "/admin" : "/user");
  }

  next();
});

export default router;
