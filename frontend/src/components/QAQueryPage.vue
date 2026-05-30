<template>
  <div class="qa-page">
    <div class="page-header">
      <h2 class="page-title">
        <el-icon><ChatDotRound /></el-icon>
        合同条款咨询
      </h2>
      <p class="page-desc">输入合同条款相关问题，AI 将根据相关法律为您提供专业分析和建议</p>
    </div>

    <el-row :gutter="24">
      <el-col :span="12">
        <el-card shadow="hover" class="q-card">
          <template #header>
            <div class="card-header">
              <el-icon><Edit /></el-icon>
              <span>请输入合同条款相关问题</span>
            </div>
          </template>

          <el-input
            v-model="question"
            type="textarea"
            :rows="12"
            placeholder="请输入合同条款相关问题..."
            class="qa-input"
          />
          <el-button
            type="primary"
            size="large"
            class="submit-btn"
            :loading="loading"
            @click="handleAsk"
          >
            <el-icon><Search /></el-icon>
            {{ loading ? "查询中..." : "开始咨询" }}
          </el-button>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card shadow="hover" class="result-card">
          <template #header>
            <div class="card-header">
              <el-icon><Document /></el-icon>
              <span>咨询结果</span>
              <el-tag v-if="meta.contract_type" size="small" type="info" style="margin-left: 8px">
                {{ contractTypeLabel }}
              </el-tag>
            </div>
          </template>

          <div v-if="loading" class="loading-state">
            <el-icon :size="48" class="loading-icon"><Loading /></el-icon>
            <p>AI 正在检索法律条文并生成回答...</p>
          </div>

          <div v-else-if="result" class="result-text">
            <el-alert
              v-for="(w, i) in warnings"
              :key="i"
              :title="w"
              type="warning"
              show-icon
              :closable="false"
              style="margin-bottom: 12px"
            />
            <ReviewResult :output="result" />
          </div>

          <div v-else class="empty-state">
            <el-icon :size="64"><ChatDotRound /></el-icon>
            <p>请输入问题开始法律咨询</p>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed } from "vue";
import { ChatDotRound, Edit, Search, Document, Loading } from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { submitQA } from "../api/review";
import ReviewResult from "./ReviewResult.vue";

const question = ref("");
const loading = ref(false);
const result = ref("");
const meta = ref({ contract_type: "", branches: [] });
const warnings = ref([]);

const contractTypeLabel = computed(() => {
  const t = meta.value.contract_type;
  if (t === "labor") return "劳动法领域";
  if (t === "civil") return "民事领域";
  return t;
});

async function handleAsk() {
  if (!question.value.trim()) {
    ElMessage.warning("请输入问题");
    return;
  }
  loading.value = true;
  result.value = "";
  meta.value = { contract_type: "", branches: [] };
  warnings.value = [];
  try {
    const { data } = await submitQA(question.value);
    result.value = data.review_output || "";
    meta.value = {
      contract_type: data.contract_type || "",
      branches: data.branches || [],
    };
    warnings.value = data.warnings || [];
  } catch (e) {
    ElMessage.error("查询失败：" + (e.response?.data?.detail || e.message));
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.qa-page { padding: 4px; }
.page-header { margin-bottom: 20px; }
.page-title { display: flex; align-items: center; gap: 8px; font-size: 22px; color: #303133; margin: 0 0 8px 0; }
.page-desc { color: #909399; margin: 0; font-size: 14px; }
.q-card, .result-card { height: calc(100vh - 200px); display: flex; flex-direction: column; }
.q-card :deep(.el-card__body) { flex: 1; display: flex; flex-direction: column; }
.result-card :deep(.el-card__body) { flex: 1; overflow-y: auto; }
.card-header { display: flex; align-items: center; gap: 6px; font-weight: 600; }
.qa-input { flex: 1; margin-bottom: 16px; }
.qa-input :deep(textarea) { min-height: 200px !important; font-size: 14px; line-height: 1.8; }
.submit-btn { width: 100%; }
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #c0c4cc; }
.empty-state p { margin-top: 16px; font-size: 14px; }
.loading-state { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #909399; }
.loading-state p { margin-top: 16px; font-size: 14px; }
.loading-icon { color: #409eff; animation: spin 1.2s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.result-text { font-size: 14px; line-height: 1.8; color: #303133; }
</style>
