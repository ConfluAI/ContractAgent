<template>
  <div class="qa-page">
    <div class="qa-layout">
      <!-- 左侧：会话列表 -->
      <div class="thread-sidebar" :class="{ collapsed: sidebarCollapsed }">
        <div class="sidebar-header">
          <span v-if="!sidebarCollapsed" class="sidebar-title">对话记录</span>
          <el-button
            size="small"
            text
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            <el-icon><component :is="sidebarCollapsed ? DArrowRight : DArrowLeft" /></el-icon>
          </el-button>
        </div>
        <template v-if="!sidebarCollapsed">
          <el-button
            type="primary"
            size="small"
            class="new-thread-btn"
            @click="selectThread(null)"
          >
            <el-icon><Plus /></el-icon>
            新建对话
          </el-button>
          <div class="thread-list" v-loading="threadsLoading">
            <div
              v-for="t in threads"
              :key="t.id"
              class="thread-item"
              :class="{ active: t.id === threadId }"
              @click="selectThread(t.id)"
            >
              <div class="thread-title">{{ t.title || '新对话' }}</div>
              <div class="thread-meta">
                <span>{{ t.contract_type === 'labor' ? '劳动法' : '民事' }}</span>
                <span class="thread-date">{{ formatDate(t.updated_at) }}</span>
              </div>
              <el-button
                class="thread-delete"
                size="small"
                text
                @click.stop="removeThread(t.id)"
              >
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-empty v-if="!threadsLoading && threads.length === 0" description="暂无对话" :image-size="48" />
          </div>
        </template>
      </div>

      <!-- 右侧：主区域 -->
      <div class="qa-main">
        <!-- 对话消息展示 -->
        <div class="messages-area" ref="messagesArea">
          <div v-if="chatMessages.length === 0 && !loading" class="welcome-msg">
            <el-icon :size="48" color="#409eff"><ChatDotRound /></el-icon>
            <p>输入问题开始法律咨询</p>
            <p class="welcome-hint">AI 将检索民法典及专项法律条文为您解答</p>
          </div>

          <div v-for="(msg, i) in chatMessages" :key="i" class="message-bubble" :class="msg.role">
            <div class="msg-label">{{ msg.role === 'user' ? '您' : 'AI' }}</div>
            <div class="msg-content">
              <ReviewResult v-if="msg.role === 'assistant'" :output="msg.content" />
              <span v-else>{{ msg.content }}</span>
            </div>
          </div>

          <!-- 流式生成中 -->
          <div v-if="streamPhase === 'generating'" class="message-bubble assistant">
            <div class="msg-label">AI <span class="generating-dot">●</span></div>
            <div class="msg-content">
              <ReviewResult :output="streamOutput" />
              <span class="cursor-blink">|</span>
            </div>
          </div>
        </div>

        <!-- 底部输入区 -->
        <div class="input-area">
          <el-input
            v-model="question"
            type="textarea"
            :rows="3"
            placeholder="请输入合同条款相关问题..."
            class="qa-input"
            @keydown.enter.exact.prevent="handleAsk"
          />
          <el-button
            type="primary"
            :loading="loading"
            :disabled="!question.trim()"
            @click="handleAsk"
          >
            <el-icon><Promotion /></el-icon>
            {{ loading ? (streamPhase === 'retrieval' ? '检索中' : '生成中') : '发送' }}
          </el-button>
        </div>

        <!-- 追问状态栏 -->
        <div v-if="threadId" class="status-bar">
          <el-tag type="info" size="small" effect="plain">
            追问模式 · {{ meta.contract_type === 'labor' ? '劳动法领域' : '民事领域' }}
          </el-tag>
          <el-alert
            v-for="(w, i) in warnings"
            :key="i"
            :title="w"
            type="warning"
            :closable="false"
            style="margin-top: 4px"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, watch } from "vue";
import { ChatDotRound, Plus, Promotion, DArrowLeft, DArrowRight, Delete } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { submitQAStream, submitQA } from "../api/review";
import { listThreads, getMessages, deleteThread } from "../api/threads";
import ReviewResult from "./ReviewResult.vue";

const question = ref("");
const loading = ref(false);
const streamOutput = ref("");
const streamPhase = ref(""); // '' | 'retrieval' | 'generating'
const meta = ref({ contract_type: "", branches: [] });
const warnings = ref([]);
const threadId = ref(null);
const chatMessages = ref([]);
const threads = ref([]);
const threadsLoading = ref(false);
const sidebarCollapsed = ref(false);
const messagesArea = ref(null);

let streamCtrl = null;

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const diff = now - d;
  if (diff < 3600000) return Math.floor(diff / 60000) + "分钟前";
  if (diff < 86400000) return Math.floor(diff / 3600000) + "小时前";
  return d.toLocaleDateString("zh-CN");
}

async function loadThreads() {
  threadsLoading.value = true;
  try {
    const { data } = await listThreads();
    threads.value = data;
  } catch {
    // 静默处理
  } finally {
    threadsLoading.value = false;
  }
}

async function selectThread(id) {
  if (streamCtrl) { streamCtrl.abort(); streamCtrl = null; }
  loading.value = false;
  streamPhase.value = "";
  streamOutput.value = "";
  warnings.value = [];

  if (!id) {
    threadId.value = null;
    chatMessages.value = [];
    question.value = "";
    return;
  }

  threadId.value = id;
  chatMessages.value = [];
  try {
    const { data } = await getMessages(id);
    chatMessages.value = data.map(m => ({ role: m.role, content: m.content }));
    await nextTick();
    scrollToBottom();
  } catch {
    ElMessage.error("加载对话记录失败");
  }
}

async function removeThread(id) {
  try {
    await ElMessageBox.confirm("确定删除这个对话？对话记录将永久删除。", "确认删除", {
      confirmButtonText: "删除",
      cancelButtonText: "取消",
      type: "warning",
    });
    await deleteThread(id);
    if (threadId.value === id) selectThread(null);
    await loadThreads();
    ElMessage.success("已删除");
  } catch (err) {
    if (err !== "cancel" && err?.action !== "cancel") {
      ElMessage.error("删除失败");
    }
  }
}

function scrollToBottom() {
  if (messagesArea.value) {
    messagesArea.value.scrollTop = messagesArea.value.scrollHeight;
  }
}

watch(streamOutput, () => nextTick(() => scrollToBottom()));
watch(chatMessages, () => nextTick(() => scrollToBottom()), { deep: true });

function resetInput() {
  if (streamCtrl) { streamCtrl.abort(); streamCtrl = null; }
  loading.value = false;
  streamPhase.value = "";
  streamOutput.value = "";
  warnings.value = [];
  question.value = "";
}

async function handleAsk() {
  if (!question.value.trim()) return;

  const q = question.value;
  question.value = "";
  loading.value = true;
  streamPhase.value = "retrieval";
  streamOutput.value = "";
  warnings.value = [];

  chatMessages.value.push({ role: "user", content: q });

  streamCtrl = submitQAStream(q, threadId.value, {
    onEvent(event, data) {
      if (event === "retrieval_done") {
        streamPhase.value = "generating";
        meta.value = {
          contract_type: data.contract_type || "",
          branches: data.branches || [],
        };
        warnings.value = data.warnings || [];
      } else if (event === "retry") {
        streamOutput.value = "";
        ElMessage.info(`生成超时，正在重试 (${data.attempt}/${data.max_retries})...`);
      } else if (event === "token") {
        streamOutput.value += data.token;
      } else if (event === "done") {
        loading.value = false;
        streamPhase.value = "";
        streamCtrl = null;
        const finalText = streamOutput.value || data.full_output;
        if (finalText) {
          chatMessages.value.push({ role: "assistant", content: finalText });
        }
        streamOutput.value = "";
        if (data.thread_id) threadId.value = data.thread_id;
        if (!threadId.value || data.thread_id !== threadId.value) {
          loadThreads();
        }
        if (data.error) ElMessage.error(data.error);
      }
    },
    onError(err) {
      streamCtrl = null;
      // 如果流式已经收到了一些 token，保留
      if (streamOutput.value) {
        chatMessages.value.push({ role: "assistant", content: streamOutput.value });
        streamOutput.value = "";
      }
      // 兜底：切到阻塞 API
      fallbackToBlocking(q);
    },
    onComplete() {
      loading.value = false;
      streamPhase.value = "";
      streamCtrl = null;
    },
  });
}

async function fallbackToBlocking(q) {
  loading.value = true;
  streamPhase.value = "";
  ElMessage.info("正在切换为普通模式...");
  try {
    const { data } = await submitQA(q);
    if (data.error) {
      ElMessage.error(data.error);
    } else {
      chatMessages.value.push({ role: "assistant", content: data.review_output });
      if (data.id && !threadId.value) {
        threadId.value = "blocking-" + data.id;
        loadThreads();
      }
    }
  } catch (e) {
    ElMessage.error("普通模式也失败了：" + (e.response?.data?.detail || e.message));
  } finally {
    loading.value = false;
  }
}

onMounted(() => loadThreads());
</script>

<style scoped>
.qa-page { height: calc(100vh - 120px); }
.qa-layout { display: flex; gap: 16px; height: 100%; }

/* 侧边栏 */
.thread-sidebar {
  width: 260px;
  min-width: 260px;
  background: #fff;
  border-radius: 12px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  transition: width 0.2s, min-width 0.2s;
}
.thread-sidebar.collapsed {
  width: 48px;
  min-width: 48px;
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.sidebar-title { font-weight: 600; font-size: 14px; }
.new-thread-btn { width: 100%; margin-bottom: 8px; }
.thread-list { flex: 1; overflow-y: auto; }
.thread-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  position: relative;
  margin-bottom: 4px;
  border: 1px solid transparent;
}
.thread-item:hover { background: #f5f7fa; }
.thread-item.active { background: #ecf5ff; border-color: #409eff; }
.thread-title { font-size: 13px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding-right: 24px; }
.thread-meta { font-size: 11px; color: #909399; margin-top: 2px; display: flex; gap: 8px; }
.thread-delete { position: absolute; right: 4px; top: 4px; opacity: 0.4; }
.thread-item:hover .thread-delete { opacity: 1; }

/* 主区域 */
.qa-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.messages-area { flex: 1; overflow-y: auto; padding: 16px; background: #fff; border-radius: 12px; margin-bottom: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
.welcome-msg { text-align: center; padding: 80px 20px; color: #909399; }
.welcome-msg p { margin-top: 12px; font-size: 15px; }
.welcome-hint { font-size: 13px; color: #c0c4cc; }

/* 消息气泡 */
.message-bubble { margin-bottom: 20px; }
.msg-label { font-size: 12px; color: #909399; margin-bottom: 4px; }
.message-bubble.user .msg-label { text-align: right; }
.message-bubble.assistant .msg-content { background: #f5f7fa; border-radius: 8px; padding: 12px 16px; }
.message-bubble.user .msg-content { text-align: right; }
.generating-dot { color: #409eff; animation: pulse 1s infinite; }

/* 输入区 */
.input-area { display: flex; gap: 8px; align-items: flex-end; background: #fff; padding: 12px; border-radius: 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }
.qa-input { flex: 1; }

.status-bar { margin-top: 8px; text-align: center; }

.cursor-blink { animation: blink 1s step-end infinite; color: #409eff; font-weight: bold; font-size: 18px; }
@keyframes blink { 50% { opacity: 0; } }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
</style>
