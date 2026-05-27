<template>
  <div class="users-page">
    <div class="page-header">
      <h2 class="page-title">
        <el-icon><UserFilled /></el-icon>
        用户管理
      </h2>
      <p class="page-desc">管理系统用户账号和权限分配</p>
    </div>

    <el-card shadow="hover" class="users-card">
      <template #header>
        <div class="card-header">
          <div class="header-left">
            <span>用户列表</span>
            <el-tag size="small" type="info" effect="plain">共 {{ users.length }} 人</el-tag>
          </div>
          <el-button type="primary" text size="small" @click="loadUsers">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-table
        :data="users"
        stripe
        style="width: 100%"
        v-loading="loading"
        :header-cell-style="{ background: '#fafafa', fontWeight: 600 }"
      >
        <el-table-column prop="id" label="ID" width="70" align="center" />
        <el-table-column label="用户名" min-width="150">
          <template #default="{ row }">
            <div class="user-cell">
              <el-avatar :size="32" class="user-avatar-sm">
                {{ row.username?.[0]?.toUpperCase() }}
              </el-avatar>
              <span class="user-name">{{ row.username }}</span>
              <el-tag v-if="row.id === currentUserId" size="small" type="info" effect="plain">当前</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="160" align="center">
          <template #default="{ row }">
            <el-select
              :model-value="row.role"
              @change="(val) => handleRoleChange(row.id, val)"
              size="small"
              style="width: 120px"
            >
              <el-option label="管理员" value="admin">
                <span style="display: flex; align-items: center; gap: 6px">
                  <el-tag type="danger" size="small" effect="dark">管理员</el-tag>
                </span>
              </el-option>
              <el-option label="普通用户" value="user">
                <span style="display: flex; align-items: center; gap: 6px">
                  <el-tag type="primary" size="small" effect="dark">普通用户</el-tag>
                </span>
              </el-option>
            </el-select>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="注册时间" width="190" align="center">
          <template #default="{ row }">
            <span class="time-text">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-popconfirm
              title="确定删除该用户？此操作不可恢复。"
              @confirm="handleDelete(row.id)"
            >
              <template #reference>
                <el-button
                  type="danger"
                  size="small"
                  text
                  :disabled="row.id === currentUserId"
                >
                  <el-icon><Delete /></el-icon>
                  删除
                </el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { getUsers, deleteUser, updateRole } from "../../api/users";
import { useAuthStore } from "../../stores/auth";
import { ElMessage } from "element-plus";

const authStore = useAuthStore();
const currentUserId = computed(() => authStore.user?.id);
const users = ref([]);
const loading = ref(false);

function formatTime(t) {
  if (!t) return "-";
  return t.replace("T", " ").substring(0, 19);
}

async function loadUsers() {
  loading.value = true;
  try {
    const { data } = await getUsers();
    users.value = data.users;
  } finally {
    loading.value = false;
  }
}

async function handleDelete(id) {
  await deleteUser(id);
  ElMessage.success("删除成功");
  loadUsers();
}

async function handleRoleChange(id, role) {
  await updateRole(id, role);
  ElMessage.success("角色更新成功");
  loadUsers();
}

onMounted(loadUsers);
</script>

<style scoped>
.users-page {
  max-width: 1200px;
}
.page-header {
  margin-bottom: 24px;
}
.page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 22px;
  color: #303133;
  margin: 0 0 8px;
}
.page-desc {
  font-size: 14px;
  color: #909399;
  margin: 0;
}
.users-card {
  border-radius: 12px;
  border: none;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 15px;
}
.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-avatar-sm {
  background: linear-gradient(135deg, #409eff, #6366f1);
  color: #fff;
  font-weight: 600;
  font-size: 13px;
  flex-shrink: 0;
}
.user-name {
  font-weight: 500;
}
.time-text {
  font-size: 13px;
  color: #909399;
}
</style>
