# 测试案例配置说明

## 配置继承机制

为了减少配置冗余，测试系统现在支持配置继承机制：

### 1. 公共配置 (common.json)

`common.json` 文件包含所有测试案例的默认配置：

```json
{
    "defaultConfig": {
        "modelName": "Tome-Max",
        "api": "https://pre.anydata.aishu.cn:8444/api/model-factory/v1/chat/completions",
        "typeApi": "openai",
        "userId": "8cfc5d1e-d535-11ee-a2b0-42a9aad9dca0",
        "maxTokens": 1000,
        "temperature": 0.0
    }
}
```

### 2. 测试案例文件配置

每个 `*_cases.json` 文件可以：

1. **使用公共配置**：如果 `testSuite` 中没有 `defaultConfig`，将自动使用 `common.json` 中的配置
2. **覆盖特定配置**：如果 `testSuite` 中有 `defaultConfig`，将与公共配置合并，本地配置优先

## 使用示例

### 使用公共配置的测试文件

```json
{
  "testSuite": {
    "name": "Basic Test Cases",
    "description": "使用公共配置的测试案例",
    "version": "1.0.0"
  },
  "testCases": [
    // 测试案例将使用 common.json 中的所有配置
  ]
}
```

### 覆盖特定配置的测试文件

```json
{
  "testSuite": {
    "name": "Custom Config Test Cases",
    "description": "需要特殊配置的测试案例",
    "version": "1.0.0",
    "defaultConfig": {
      "temperature": 0.8,
      "maxTokens": 2000
    }
  },
  "testCases": [
    // 测试案例将使用：
    // - temperature: 0.8 (覆盖)
    // - maxTokens: 2000 (覆盖)
    // - 其他配置从 common.json 继承
  ]
}
```

## 配置优先级

1. **最高优先级**：测试案例文件中的 `testSuite.defaultConfig`
2. **默认配置**：`common.json` 中的 `defaultConfig`

## 注意事项

- `common.json` 文件会被自动加载，不会作为测试案例文件处理
- 配置合并是浅层合并，即只合并顶层属性
- 如果 `common.json` 不存在或加载失败，会显示警告信息但不会影响测试执行
- 所有现有的测试案例文件已经移除了冗余的 `defaultConfig`，现在都使用公共配置 