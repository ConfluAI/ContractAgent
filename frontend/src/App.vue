<template>
  <router-view />
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  --el-color-primary: #2c5ea8;
  --el-color-primary-light-3: #4d7abf;
  --el-color-primary-light-5: #7da1d1;
  --el-color-primary-light-7: #b3c8e4;
  --el-color-primary-light-8: #ccdaf0;
  --el-color-primary-light-9: #e5edf7;
  --el-color-primary-dark-2: #234b86;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: #303133;
}

a {
  color: #2c5ea8;
  text-decoration: none;
}

::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-thumb {
  background: #c0c4cc;
  border-radius: 3px;
}

::-webkit-scrollbar-track {
  background: transparent;
}
</style>
