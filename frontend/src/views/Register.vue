<template>
  <div class="register-container">
    <div class="register-bg">
      <div class="shape shape-1"></div>
      <div class="shape shape-2"></div>
      <div class="shape shape-3"></div>
    </div>
    <el-card class="register-card" shadow="always">
      <div class="register-header">
        <div class="logo-icon">
          <el-icon :size="36"><Document /></el-icon>
        </div>
        <h1 class="register-title">创建账号</h1>
        <p class="register-subtitle">注册后即可使用合同审查功能</p>
      </div>
      <el-form :model="form" @submit.prevent="handleRegister" label-width="0" class="register-form">
        <el-form-item>
          <el-input
            v-model="form.username"
            placeholder="请输入用户名（3-50个字符）"
            prefix-icon="User"
            size="large"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码（至少6位）"
            prefix-icon="Lock"
            size="large"
            show-password
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.confirmPassword"
            type="password"
            placeholder="请再次输入密码"
            prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleRegister"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            class="register-btn"
            :loading="loading"
            native-type="submit"
          >
            注 册
          </el-button>
        </el-form-item>
      </el-form>
      <div class="register-footer">
        <span>已有账号？</span>
        <router-link to="/login" class="login-link">返回登录</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { ElMessage } from "element-plus";

const authStore = useAuthStore();
const router = useRouter();
const loading = ref(false);
const form = reactive({ username: "", password: "", confirmPassword: "" });

async function handleRegister() {
  if (!form.username || !form.password) {
    ElMessage.warning("请输入用户名和密码");
    return;
  }
  if (form.password !== form.confirmPassword) {
    ElMessage.warning("两次密码输入不一致");
    return;
  }
  loading.value = true;
  try {
    await authStore.register(form.username, form.password, "user");
    ElMessage.success("注册成功，请登录");
    router.push("/login");
  } catch {
    // error already handled by interceptor
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.register-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  position: relative;
  overflow: hidden;
}
.register-bg {
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
  width: 350px;
  height: 350px;
  background: #67c23a;
  top: -80px;
  left: -80px;
  animation: float 9s ease-in-out infinite;
}
.shape-2 {
  width: 250px;
  height: 250px;
  background: #409eff;
  bottom: -60px;
  right: -60px;
  animation: float 7s ease-in-out infinite reverse;
}
.shape-3 {
  width: 180px;
  height: 180px;
  background: #e6a23c;
  top: 40%;
  right: 55%;
  animation: float 11s ease-in-out infinite;
}
@keyframes float {
  0%, 100% { transform: translateY(0) scale(1); }
  50% { transform: translateY(-25px) scale(1.04); }
}
.register-card {
  width: 440px;
  padding: 10px 20px 20px;
  border-radius: 16px;
  border: none;
  position: relative;
  z-index: 1;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(20px);
}
.register-header {
  text-align: center;
  margin-bottom: 28px;
}
.logo-icon {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: linear-gradient(135deg, #67c23a, #409eff);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
  color: #fff;
  box-shadow: 0 8px 24px rgba(103, 194, 58, 0.3);
}
.register-title {
  font-size: 26px;
  color: #1a1a2e;
  margin: 0 0 8px;
  font-weight: 700;
}
.register-subtitle {
  font-size: 14px;
  color: #909399;
  margin: 0;
}
.register-form :deep(.el-input__wrapper) {
  border-radius: 10px;
  padding: 4px 12px;
}
.register-btn {
  width: 100%;
  border-radius: 10px;
  font-size: 16px;
  height: 44px;
  background: linear-gradient(135deg, #67c23a, #409eff);
  border: none;
  letter-spacing: 4px;
}
.register-btn:hover {
  background: linear-gradient(135deg, #85ce61, #66b1ff);
}
.register-footer {
  text-align: center;
  margin-top: 16px;
  font-size: 14px;
  color: #909399;
}
.login-link {
  color: #409eff;
  text-decoration: none;
  margin-left: 4px;
  font-weight: 500;
}
.login-link:hover {
  text-decoration: underline;
}
</style>
