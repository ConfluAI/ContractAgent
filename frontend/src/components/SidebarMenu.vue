<template>
  <div class="sidebar-logo">
    <div class="logo-icon">
      <el-icon :size="24"><Document /></el-icon>
    </div>
    <div class="logo-text">
      <div class="logo-title">合同审查智能体</div>
      <div class="logo-badge">{{ isAdmin ? "管理后台" : "用户中心" }}</div>
    </div>
  </div>

  <div class="sidebar-user">
    <el-avatar :size="40" class="user-avatar">
      {{ authStore.user?.username?.[0]?.toUpperCase() }}
    </el-avatar>
    <div class="user-info">
      <div class="user-name">{{ authStore.user?.username }}</div>
      <div class="user-role">{{ isAdmin ? "管理员" : "普通用户" }}</div>
    </div>
  </div>

  <el-menu
    :default-active="$route.path"
    :router="true"
    background-color="transparent"
    text-color="rgba(255,255,255,0.65)"
    active-text-color="#fff"
    class="sidebar-menu"
  >
    <el-menu-item :index="dashboardPath">
      <el-icon><HomeFilled /></el-icon>
      <span>{{ isAdmin ? "管理首页" : "个人信息" }}</span>
    </el-menu-item>

    <el-menu-item v-if="isAdmin" index="/admin/users">
      <el-icon><UserFilled /></el-icon>
      <span>用户管理</span>
    </el-menu-item>

    <div class="menu-divider">
      <span>功能区</span>
    </div>

    <el-menu-item :index="reviewPath">
      <el-icon><Document /></el-icon>
      <span>合同审查</span>
    </el-menu-item>

    <el-menu-item :index="historyPath">
      <el-icon><Clock /></el-icon>
      <span>查询历史</span>
    </el-menu-item>
  </el-menu>

  <div class="sidebar-footer">
    <div class="footer-text">Powered by AI</div>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useAuthStore } from "../stores/auth";

const authStore = useAuthStore();
const isAdmin = computed(() => authStore.user?.role === "admin");
const dashboardPath = computed(() => isAdmin.value ? "/admin/dashboard" : "/user/dashboard");
const reviewPath = computed(() => isAdmin.value ? "/admin/review" : "/user/review");
const historyPath = computed(() => isAdmin.value ? "/admin/history" : "/user/history");
</script>

<style scoped>
.sidebar-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 20px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.logo-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  background: linear-gradient(135deg, #409eff, #6366f1);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.logo-title {
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 1px;
}
.logo-badge {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.45);
  margin-top: 2px;
}
.sidebar-user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.user-avatar {
  background: linear-gradient(135deg, #e6a23c, #f56c6c);
  color: #fff;
  font-weight: 600;
  flex-shrink: 0;
}
.user-name {
  font-size: 14px;
  color: #fff;
  font-weight: 500;
}
.user-role {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.45);
  margin-top: 2px;
}
.sidebar-menu {
  border-right: none;
  padding: 8px 0;
}
.sidebar-menu :deep(.el-menu-item) {
  height: 46px;
  line-height: 46px;
  margin: 2px 10px;
  border-radius: 8px;
  transition: all 0.2s;
}
.sidebar-menu :deep(.el-menu-item:hover) {
  background: rgba(255, 255, 255, 0.08) !important;
}
.sidebar-menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.3), rgba(99, 102, 241, 0.3)) !important;
  font-weight: 600;
}
.menu-divider {
  padding: 16px 24px 8px;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.25);
  text-transform: uppercase;
  letter-spacing: 2px;
}
.sidebar-footer {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 16px;
  text-align: center;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.footer-text {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.2);
  letter-spacing: 1px;
}
</style>
