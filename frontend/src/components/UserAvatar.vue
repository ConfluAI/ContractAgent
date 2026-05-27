<template>
  <el-dropdown @command="handleCommand" trigger="click">
    <div class="avatar-trigger">
      <el-avatar :size="36" class="header-avatar">
        {{ authStore.user?.username?.[0]?.toUpperCase() }}
      </el-avatar>
      <div class="avatar-info">
        <div class="avatar-name">{{ authStore.user?.username }}</div>
        <div class="avatar-role">{{ authStore.user?.role === "admin" ? "管理员" : "普通用户" }}</div>
      </div>
      <el-icon class="avatar-arrow"><ArrowDown /></el-icon>
    </div>
    <template #dropdown>
      <el-dropdown-menu>
        <div class="dropdown-header">
          <el-avatar :size="48" class="dropdown-avatar">
            {{ authStore.user?.username?.[0]?.toUpperCase() }}
          </el-avatar>
          <div class="dropdown-info">
            <div class="dropdown-name">{{ authStore.user?.username }}</div>
            <el-tag :type="authStore.user?.role === 'admin' ? 'danger' : 'primary'" size="small" effect="dark">
              {{ authStore.user?.role === "admin" ? "管理员" : "普通用户" }}
            </el-tag>
          </div>
        </div>
        <el-dropdown-item divided command="logout">
          <el-icon><SwitchButton /></el-icon>
          退出登录
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<script setup>
import { useAuthStore } from "../stores/auth";

const authStore = useAuthStore();

function handleCommand(cmd) {
  if (cmd === "logout") {
    authStore.logout();
  }
}
</script>

<style scoped>
.avatar-trigger {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background 0.2s;
}
.avatar-trigger:hover {
  background: #f5f7fa;
}
.header-avatar {
  background: linear-gradient(135deg, #409eff, #6366f1);
  color: #fff;
  font-weight: 600;
  flex-shrink: 0;
}
.avatar-info {
  line-height: 1.3;
}
.avatar-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.avatar-role {
  font-size: 11px;
  color: #909399;
}
.avatar-arrow {
  color: #909399;
  font-size: 12px;
}
.dropdown-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
}
.dropdown-avatar {
  background: linear-gradient(135deg, #409eff, #6366f1);
  color: #fff;
  font-weight: 600;
  flex-shrink: 0;
}
.dropdown-name {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 4px;
}
</style>
