<template>
  <div class="review-result" v-html="formattedOutput" />
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  output: { type: String, default: "" },
});

const formattedOutput = computed(() => {
  if (!props.output) return "";
  let text = props.output;

  // Headings
  text = text.replace(/^### (.+)$/gm, '<h3 class="result-h3">$1</h3>');
  text = text.replace(/^## (.+)$/gm, '<h2 class="result-h2">$1</h2>');
  text = text.replace(/^# (.+)$/gm, '<h1 class="result-h1">$1</h1>');

  // Bold
  text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // Tables
  text = text.replace(/^\| (.+)$/gm, (match) => {
    const cells = match.split("|").filter(Boolean).map((c) => c.trim());
    return "<tr>" + cells.map((c) => `<td>${c}</td>`).join("") + "</tr>";
  });
  text = text.replace(/(<tr>.*<\/tr>\n?)+/g, (match) => {
    const rows = match.trim();
    const firstRow = rows.match(/<tr>(.*?)<\/tr>/)?.[1] || "";
    const isHeader = firstRow.includes("---");
    if (isHeader) return "";
    const headerCells = firstRow.replace(/<td>/g, '<th>').replace(/<\/td>/g, '</th>');
    const bodyRows = rows.replace(firstRow, "");
    return `<table class="result-table"><thead><tr>${headerCells}</tr></thead><tbody>${bodyRows}</tbody></table>`;
  });

  // Lists
  text = text.replace(/^- (.+)$/gm, '<li>$1</li>');
  text = text.replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul class="result-list">${match}</ul>`);

  // Numbered lists
  text = text.replace(/^(\d+)\. (.+)$/gm, '<li class="num-item">$2</li>');

  // Line breaks
  text = text.replace(/\n/g, "<br>");
  text = text.replace(/<br><br>/g, "<br>");
  text = text.replace(/<br>(<\/?(?:h[1-3]|table|ul|li|thead|tbody|tr|th|td))/g, "$1");
  text = text.replace(/(<\/(?:h[1-3]|table|ul|li|thead|tbody|tr|th|td)>)<br>/g, "$1");

  return text;
});
</script>

<style scoped>
.review-result {
  line-height: 1.9;
  font-size: 14px;
  color: #303133;
  padding: 4px 0;
}
.review-result :deep(.result-h1) {
  font-size: 20px;
  color: #1a1a2e;
  margin: 24px 0 12px;
  padding-bottom: 8px;
  border-bottom: 2px solid #409eff;
  font-weight: 700;
}
.review-result :deep(.result-h2) {
  font-size: 17px;
  color: #409eff;
  margin: 20px 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid #e4e7ed;
  font-weight: 600;
}
.review-result :deep(.result-h3) {
  font-size: 15px;
  color: #303133;
  margin: 16px 0 8px;
  font-weight: 600;
}
.review-result :deep(strong) {
  color: #f56c6c;
  font-weight: 600;
}
.review-result :deep(.result-table) {
  border-collapse: collapse;
  width: 100%;
  margin: 12px 0;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}
.review-result :deep(.result-table th),
.review-result :deep(.result-table td) {
  border: 1px solid #ebeef5;
  padding: 10px 14px;
  text-align: left;
}
.review-result :deep(.result-table th) {
  background: #f5f7fa;
  font-weight: 600;
  color: #303133;
}
.review-result :deep(.result-table tr:hover td) {
  background: #f5f7fa;
}
.review-result :deep(.result-list) {
  padding-left: 20px;
  margin: 8px 0;
  list-style: none;
}
.review-result :deep(.result-list li) {
  position: relative;
  padding-left: 16px;
  margin: 6px 0;
}
.review-result :deep(.result-list li::before) {
  content: "";
  position: absolute;
  left: 0;
  top: 10px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #409eff;
}
</style>
