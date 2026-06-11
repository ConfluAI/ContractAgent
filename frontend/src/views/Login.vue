<template>
  <div class="login-container">
    <div class="login-bg">
      <div class="shape shape-1"></div>
      <div class="shape shape-2"></div>
      <div class="shape shape-3"></div>
    </div>
    <el-card class="login-card" shadow="always">
      <div class="login-header">
        <div class="logo-icon">
          <el-icon :size="36"><Document /></el-icon>
        </div>
        <h1 class="login-title">合同审查智能体</h1>
        <p class="login-subtitle">AI 驱动的中国合同法律审查平台</p>
      </div>
      <el-form :model="form" @submit.prevent="handleLogin" label-width="0" class="login-form">
        <el-form-item>
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            prefix-icon="User"
            size="large"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            class="login-btn"
            :loading="loading"
            native-type="submit"
          >
            登 录
          </el-button>
        </el-form-item>
      </el-form>
      <div class="login-footer">
        <span>还没有账号？</span>
        <router-link to="/register" class="register-link">立即注册</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { useAuthStore } from "../stores/auth";
import { ElMessage } from "element-plus";

const authStore = useAuthStore();
const loading = ref(false);
const form = reactive({ username: "", password: "" });

async function handleLogin() {
  if (!form.username || !form.password) {
    ElMessage.warning("请输入用户名和密码");
    return;
  }
  loading.value = true;
  try {
    await authStore.login(form.username, form.password);
  } catch {
    // error already handled by interceptor
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  position: relative;
  overflow: hidden;
}
.login-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
}
.shape {
  position: absolute;
  border-radius: 50%;
  opacity: 0.08;
}
.shape-1 {
  width: 400px;
  height: 400px;
  background: #409eff;
  top: -100px;
  right: -100px;
  animation: float 8s ease-in-out infinite;
}
.shape-2 {
  width: 300px;
  height: 300px;
  background: #67c23a;
  bottom: -80px;
  left: -80px;
  animation: float 10s ease-in-out infinite reverse;
}
.shape-3 {
  width: 200px;
  height: 200px;
  background: #e6a23c;
  top: 50%;
  left: 60%;
  animation: float 6s ease-in-out infinite;
}
@keyframes float {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-30px) scale(1.05); }
}
.login-card {
  width: 440px;
  padding: 10px 20px 20px;
  border-radius: 16px;
  border: none;
  position: relative;
  z-index: 1;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(20px);
}
.login-header {
  text-align: center;
  margin-bottom: 32px;
}
.logo-icon {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: #2c5ea8;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
  color: #fff;
  box-shadow: 0 8px 24px rgba(44, 94, 168, 0.3);
}
.login-title {
  font-size: 26px;
  color: #1a1a2e;
  margin: 0 0 8px;
  font-weight: 700;
}
.login-subtitle {
  font-size: 14px;
  color: #909399;
  margin: 0;
}
.login-form {
  margin-top: 8px;
}
.login-form :deep(.el-input__wrapper) {
  border-radius: 10px;
  padding: 4px 12px;
}
.login-btn {
  width: 100%;
  border-radius: 10px;
  font-size: 16px;
  height: 44px;
  background: #2c5ea8;
  border: none;
  letter-spacing: 4px;
}
.login-btn:hover {
  background: #3d7abf;
}
.login-footer {
  text-align: center;
  margin-top: 16px;
  font-size: 14px;
  color: #909399;
}
.register-link {
  color: #409eff;
  text-decoration: none;
  margin-left: 4px;
  font-weight: 500;
}
.register-link:hover {
  text-decoration: underline;
}
</style>
