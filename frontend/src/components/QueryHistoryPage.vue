<template>
  <div class="history-page">
    <div class="page-header">
      <h2 class="page-title">
        <el-icon><Clock /></el-icon>
        查询历史
      </h2>
      <p class="page-desc">查看和管理您的合同审查历史记录</p>
    </div>

    <el-card shadow="hover" class="history-card">
      <template #header>
        <div class="card-header">
          <div class="header-left">
            <span>历史记录</span>
            <el-tag v-if="history.length" size="small" type="info" effect="plain">
              共 {{ history.length }} 条
            </el-tag>
          </div>
          <el-button type="primary" text size="small" @click="loadHistory">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <el-table
        :data="history"
        stripe
        style="width: 100%"
        v-loading="loading"
        :header-cell-style="{ background: '#fafafa', fontWeight: 600 }"
        row-class-name="table-row"
      >
        <el-table-column prop="id" label="ID" width="70" align="center" />
        <el-table-column label="查询内容" min-width="240">
          <template #default="{ row }">
            <div class="query-cell">
              <el-icon class="query-icon"><Document /></el-icon>
              <el-tooltip :content="row.query_input" placement="top" :show-after="300">
                <span class="query-text">
                  {{ row.query_input?.substring(0, 60) }}{{ row.query_input?.length > 60 ? '...' : '' }}
                </span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="contract_type" label="合同类型" width="110" align="center">
          <template #default="{ row }">
            <el-tag
              v-if="row.contract_type"
              size="small"
              :type="row.contract_type === 'labor' ? 'warning' : row.contract_type === 'civil' ? 'primary' : 'success'"
              effect="plain"
            >
              {{ typeLabel(row.contract_type) }}
            </el-tag>
            <span v-else class="no-data">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="审查时间" width="180" align="center">
          <template #default="{ row }">
            <span class="time-text">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <el-button type="primary" size="small" text @click="showDetail(row)">
              <el-icon><View /></el-icon>
              查看
            </el-button>
            <el-popconfirm title="确定删除该记录？" @confirm="handleDelete(row.id)">
              <template #reference>
                <el-button type="danger" size="small" text>
                  <el-icon><Delete /></el-icon>
                  删除
                </el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <div v-if="!loading && history.length === 0" class="empty-state">
        <el-icon :size="56" color="#c0c4cc"><Clock /></el-icon>
        <p>暂无审查记录</p>
        <el-button type="primary" plain @click="$router.push(reviewPath)">开始第一次审查</el-button>
      </div>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      title="审查报告详情"
      width="750px"
      destroy-on-close
      top="5vh"
    >
      <ReviewResult :output="currentReview" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { getHistory, deleteHistory } from "../api/history";
import { useAuthStore } from "../stores/auth";
import { ElMessage } from "element-plus";
import ReviewResult from "./ReviewResult.vue";

const authStore = useAuthStore();
const reviewPath = computed(() => authStore.user?.role === "admin" ? "/admin/review" : "/user/review");

const history = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const currentReview = ref("");

function typeLabel(t) {
  return { labor: "劳动", civil: "民事", mixed: "混合" }[t] || t;
}

function formatTime(t) {
  if (!t) return "-";
  return t.replace("T", " ").substring(0, 19);
}

async function loadHistory() {
  loading.value = true;
  try {
    const { data } = await getHistory();
    history.value = data.items;
  } finally {
    loading.value = false;
  }
}

function showDetail(row) {
  currentReview.value = row.review_output || "无审查报告";
  dialogVisible.value = true;
}

async function handleDelete(id) {
  await deleteHistory(id);
  ElMessage.success("删除成功");
  loadHistory();
}

onMounted(loadHistory);
</script>

<style scoped>
.history-page {
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
.history-card {
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
.query-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.query-icon {
  color: #909399;
  flex-shrink: 0;
}
.query-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.time-text {
  font-size: 13px;
  color: #909399;
}
.no-data {
  color: #c0c4cc;
}
.empty-state {
  text-align: center;
  padding: 48px 20px;
  color: #909399;
}
.empty-state p {
  margin: 16px 0;
  font-size: 15px;
}
</style>
