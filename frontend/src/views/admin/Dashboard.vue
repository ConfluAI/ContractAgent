<template>
  <div class="dashboard">
    <div class="welcome-banner">
      <div class="welcome-content">
        <h2 class="welcome-title">
          {{ greeting }}，{{ authStore.user?.username }}
          <el-tag :type="isAdmin ? 'danger' : 'primary'" size="small" effect="dark" style="margin-left: 8px">
            {{ isAdmin ? "管理员" : "用户" }}
          </el-tag>
        </h2>
        <p class="welcome-desc">
          {{ isAdmin ? "欢迎回到合同审查智能体管理后台" : "欢迎使用合同审查智能体" }}
        </p>
      </div>
      <div class="welcome-illustration">
        <el-icon :size="80" color="rgba(255,255,255,0.15)"><Document /></el-icon>
      </div>
    </div>

    <el-row :gutter="20" class="stats-row">
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card stat-card-blue">
          <div class="stat-icon">
            <el-icon :size="28"><Document /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.totalReviews }}</div>
            <div class="stat-label">累计审查</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card stat-card-green">
          <div class="stat-icon">
            <el-icon :size="28"><Clock /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.todayReviews }}</div>
            <div class="stat-label">今日审查</div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover" class="stat-card stat-card-orange">
          <div class="stat-icon">
            <el-icon :size="28"><User /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ stats.totalUsers }}</div>
            <div class="stat-label">注册用户</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20">
      <el-col :span="16">
        <el-card shadow="hover" class="info-card">
          <template #header>
            <div class="card-header">
              <span>快速开始</span>
            </div>
          </template>
          <div class="quick-actions">
            <div class="action-item" @click="$router.push(reviewPath)">
              <div class="action-icon action-icon-blue">
                <el-icon :size="28"><Edit /></el-icon>
              </div>
              <div class="action-text">
                <div class="action-title">合同审查</div>
                <div class="action-desc">输入合同文本或上传文件</div>
              </div>
            </div>
            <div class="action-item" @click="$router.push(historyPath)">
              <div class="action-icon action-icon-green">
                <el-icon :size="28"><Clock /></el-icon>
              </div>
              <div class="action-text">
                <div class="action-title">查看历史</div>
                <div class="action-desc">浏览过往审查记录</div>
              </div>
            </div>
            <div v-if="isAdmin" class="action-item" @click="$router.push('/admin/users')">
              <div class="action-icon action-icon-purple">
                <el-icon :size="28"><UserFilled /></el-icon>
              </div>
              <div class="action-text">
                <div class="action-title">用户管理</div>
                <div class="action-desc">管理系统用户和权限</div>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card shadow="hover" class="info-card">
          <template #header>
            <div class="card-header">
              <span>个人信息</span>
            </div>
          </template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="用户名">{{ authStore.user?.username }}</el-descriptions-item>
            <el-descriptions-item label="角色">
              <el-tag :type="isAdmin ? 'danger' : 'primary'" size="small">
                {{ isAdmin ? "管理员" : "普通用户" }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="ID">{{ authStore.user?.id }}</el-descriptions-item>
            <el-descriptions-item label="注册时间">{{ formatTime(authStore.user?.created_at) }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, reactive, onMounted } from "vue";
import { useAuthStore } from "../../stores/auth";
import { getHistory } from "../../api/history";
import { getUsers } from "../../api/users";

const authStore = useAuthStore();
const isAdmin = computed(() => authStore.user?.role === "admin");
const reviewPath = computed(() => isAdmin.value ? "/admin/review" : "/user/review");
const historyPath = computed(() => isAdmin.value ? "/admin/history" : "/user/history");

const stats = reactive({ totalReviews: 0, todayReviews: 0, totalUsers: "-" });

const greeting = computed(() => {
  const h = new Date().getHours();
  if (h < 6) return "夜深了";
  if (h < 12) return "早上好";
  if (h < 14) return "中午好";
  if (h < 18) return "下午好";
  return "晚上好";
});

function formatTime(t) {
  if (!t) return "-";
  return t.replace("T", " ").substring(0, 19);
}

onMounted(async () => {
  try {
    const { data } = await getHistory();
    stats.totalReviews = data.total;
    const today = new Date().toISOString().substring(0, 10);
    stats.todayReviews = data.items.filter((i) => i.created_at?.startsWith(today)).length;
  } catch { /* ignore */ }

  if (isAdmin.value) {
    try {
      const { data } = await getUsers();
      stats.totalUsers = data.total;
    } catch { /* ignore */ }
  }
});
</script>

<style scoped>
.dashboard {
  max-width: 1200px;
}
.welcome-banner {
  background: linear-gradient(135deg, #409eff 0%, #6366f1 100%);
  border-radius: 16px;
  padding: 32px 40px;
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #fff;
  position: relative;
  overflow: hidden;
}
.welcome-banner::before {
  content: "";
  position: absolute;
  width: 200px;
  height: 200px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 50%;
  top: -60px;
  right: 100px;
}
.welcome-title {
  font-size: 24px;
  margin: 0 0 8px;
  font-weight: 700;
}
.welcome-desc {
  font-size: 14px;
  margin: 0;
  opacity: 0.85;
}
.welcome-illustration {
  opacity: 0.8;
}
.stats-row {
  margin-bottom: 24px;
}
.stat-card {
  border-radius: 12px;
  border: none;
  overflow: hidden;
}
.stat-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px 24px;
}
.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.stat-card-blue .stat-icon {
  background: linear-gradient(135deg, #409eff, #6366f1);
}
.stat-card-green .stat-icon {
  background: linear-gradient(135deg, #67c23a, #409eff);
}
.stat-card-orange .stat-icon {
  background: linear-gradient(135deg, #e6a23c, #f56c6c);
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
  line-height: 1;
}
.stat-label {
  font-size: 13px;
  color: #909399;
  margin-top: 4px;
}
.info-card {
  border-radius: 12px;
  border: none;
  margin-bottom: 20px;
}
.card-header {
  font-weight: 600;
  font-size: 16px;
}
.quick-actions {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.action-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  background: #fafafa;
}
.action-item:hover {
  background: #f0f7ff;
  transform: translateX(4px);
}
.action-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.action-icon-blue {
  background: linear-gradient(135deg, #409eff, #6366f1);
}
.action-icon-green {
  background: linear-gradient(135deg, #67c23a, #409eff);
}
.action-icon-purple {
  background: linear-gradient(135deg, #9b59b6, #6366f1);
}
.action-title {
  font-size: 15px;
  font-weight: 600;
  color: #303133;
}
.action-desc {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
</style>
