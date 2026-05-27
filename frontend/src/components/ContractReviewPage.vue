<template>
  <div class="review-page">
    <div class="page-header">
      <h2 class="page-title">
        <el-icon><Document /></el-icon>
        合同审查
      </h2>
      <p class="page-desc">输入合同文本或上传文件，AI 将为您生成专业的法律审查报告</p>
    </div>

    <el-row :gutter="24">
      <el-col :span="11">
        <el-card shadow="hover" class="input-card">
          <template #header>
            <div class="card-header">
              <div class="header-left">
                <el-icon><Edit /></el-icon>
                <span>审查输入</span>
              </div>
              <el-radio-group v-model="inputMode" size="small">
                <el-radio-button value="text">
                  <el-icon><EditPen /></el-icon>
                  文本输入
                </el-radio-button>
                <el-radio-button value="file">
                  <el-icon><Upload /></el-icon>
                  文件上传
                </el-radio-button>
              </el-radio-group>
            </div>
          </template>

          <div v-if="inputMode === 'text'" class="input-section">
            <el-input
              v-model="inputText"
              type="textarea"
              :rows="14"
              placeholder="请在此输入合同文本或法律问题...&#10;&#10;示例：&#10;第八条 劳动报酬：甲方有权根据经营状况决定是否发放绩效工资。&#10;第十五条 乙方连续两个月考核不合格的，甲方可立即解除劳动合同。"
              class="text-input"
            />
            <el-button
              type="primary"
              size="large"
              class="submit-btn"
              :loading="reviewing"
              @click="handleTextReview"
            >
              <el-icon><Search /></el-icon>
              {{ reviewing ? "审查中..." : "开始审查" }}
            </el-button>
          </div>

          <div v-else class="input-section">
            <el-upload
              drag
              :auto-upload="false"
              :limit="1"
              accept=".docx,.pdf"
              :on-change="handleFileChange"
              :on-exceed="() => ElMessage.warning('只能上传一个文件')"
              class="file-upload"
            >
              <div class="upload-content">
                <el-icon :size="52" class="upload-icon"><UploadFilled /></el-icon>
                <div class="upload-text">拖拽文件到此处</div>
                <div class="upload-hint">或 <em>点击选择文件</em></div>
                <div class="upload-tip">支持 .docx 和 .pdf 格式</div>
              </div>
            </el-upload>
            <el-button
              type="primary"
              size="large"
              class="submit-btn"
              :loading="reviewing"
              :disabled="!selectedFile"
              @click="handleFileReview"
            >
              <el-icon><Search /></el-icon>
              {{ reviewing ? "审查中..." : "开始审查" }}
            </el-button>
          </div>
        </el-card>
      </el-col>

      <el-col :span="13">
        <el-card shadow="hover" class="result-card">
          <template #header>
            <div class="card-header">
              <div class="header-left">
                <el-icon><Notebook /></el-icon>
                <span>审查报告</span>
              </div>
              <el-tag v-if="reviewResult" type="success" size="small" effect="plain">
                审查完成
              </el-tag>
            </div>
          </template>

          <div v-if="reviewing" class="loading-state">
            <el-icon :size="48" class="loading-icon"><Loading /></el-icon>
            <p>AI 正在分析合同并检索相关法律条文...</p>
            <p class="loading-hint">这可能需要 10-30 秒</p>
          </div>

          <ReviewResult v-else-if="reviewResult" :output="reviewResult" />

          <div v-else class="empty-state">
            <el-icon :size="64" color="#c0c4cc"><Document /></el-icon>
            <p>请输入合同文本或上传文件开始审查</p>
            <div class="tips">
              <div class="tip-item">
                <el-icon><CircleCheck /></el-icon>
                <span>支持劳动法和民法典相关合同</span>
              </div>
              <div class="tip-item">
                <el-icon><CircleCheck /></el-icon>
                <span>自动生成风险识别和修改建议</span>
              </div>
              <div class="tip-item">
                <el-icon><CircleCheck /></el-icon>
                <span>引用准确的法律条文依据</span>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { submitReview, uploadFile } from "../api/review";
import { ElMessage } from "element-plus";
import ReviewResult from "./ReviewResult.vue";

const inputMode = ref("text");
const inputText = ref("");
const selectedFile = ref(null);
const reviewing = ref(false);
const reviewResult = ref("");

function handleFileChange(file) {
  selectedFile.value = file.raw;
}

async function handleTextReview() {
  if (!inputText.value.trim()) {
    ElMessage.warning("请输入合同文本");
    return;
  }
  reviewing.value = true;
  reviewResult.value = "";
  try {
    const { data } = await submitReview(inputText.value);
    if (data.error) {
      ElMessage.error(data.error);
    } else {
      reviewResult.value = data.review_output;
      ElMessage.success("审查完成");
    }
  } finally {
    reviewing.value = false;
  }
}

async function handleFileReview() {
  if (!selectedFile.value) {
    ElMessage.warning("请选择文件");
    return;
  }
  reviewing.value = true;
  reviewResult.value = "";
  try {
    const { data } = await uploadFile(selectedFile.value);
    if (data.error) {
      ElMessage.error(data.error);
    } else {
      reviewResult.value = data.review_output;
      ElMessage.success("审查完成");
    }
  } finally {
    reviewing.value = false;
  }
}
</script>

<style scoped>
.review-page {
  max-width: 1400px;
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
.input-card,
.result-card {
  border-radius: 12px;
  border: none;
  height: 100%;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
}
.input-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.text-input :deep(.el-textarea__inner) {
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.8;
}
.submit-btn {
  width: 100%;
  height: 48px;
  border-radius: 10px;
  font-size: 16px;
  background: linear-gradient(135deg, #409eff, #6366f1);
  border: none;
}
.submit-btn:hover {
  background: linear-gradient(135deg, #66b1ff, #7c7ff7);
}
.file-upload :deep(.el-upload-dragger) {
  border-radius: 12px;
  border: 2px dashed #dcdfe6;
  padding: 40px 20px;
  transition: all 0.2s;
}
.file-upload :deep(.el-upload-dragger:hover) {
  border-color: #409eff;
}
.upload-content {
  text-align: center;
}
.upload-icon {
  color: #c0c4cc;
  margin-bottom: 12px;
}
.upload-text {
  font-size: 16px;
  color: #606266;
  margin-bottom: 4px;
}
.upload-hint {
  font-size: 13px;
  color: #909399;
}
.upload-hint em {
  color: #409eff;
  font-style: normal;
}
.upload-tip {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 12px;
}
.loading-state {
  text-align: center;
  padding: 60px 20px;
  color: #909399;
}
.loading-icon {
  color: #409eff;
  animation: spin 1.2s linear infinite;
  margin-bottom: 16px;
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.loading-hint {
  font-size: 12px;
  color: #c0c4cc;
}
.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: #909399;
}
.empty-state p {
  margin: 16px 0;
  font-size: 15px;
}
.tips {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
  margin-top: 20px;
}
.tip-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #67c23a;
}
</style>
