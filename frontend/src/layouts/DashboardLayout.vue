<template>
  <el-container class="layout-container">
    <el-aside width="240px" class="layout-aside">
      <SidebarMenu />
    </el-aside>
    <el-container>
      <el-header class="layout-header">
        <div class="header-left">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: homePath }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="$route.meta.title">{{ $route.meta.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <UserAvatar />
        </div>
      </el-header>
      <el-main class="layout-main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed } from "vue";
import SidebarMenu from "../components/SidebarMenu.vue";
import UserAvatar from "../components/UserAvatar.vue";
import { useAuthStore } from "../stores/auth";

const authStore = useAuthStore();
const homePath = computed(() => authStore.user?.role === "admin" ? "/admin/dashboard" : "/user/dashboard");
</script>

<style scoped>
.layout-container {
  height: 100vh;
}
.layout-aside {
  background: #1a2332;
  overflow-y: auto;
  box-shadow: 2px 0 12px rgba(0, 0, 0, 0.15);
}
.layout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
  padding: 0 24px;
  height: 60px;
}
.layout-main {
  background-color: #f5f7fa;
  padding: 24px;
  overflow-y: auto;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
