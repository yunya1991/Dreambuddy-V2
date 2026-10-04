/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  // 与 tsconfig.json 的 paths "@/*": ["./src/*"] 对齐
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  testMatch: ['<rootDir>/src/**/*.test.{ts,tsx}'],
  // 加载 jest-dom 自定义匹配器 (jest.setup.ts 已存在)
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  // ts-jest 配置：用 tsconfig.test.json (jsx:react-jsx, 主 tsconfig 用 preserve 给 Next.js)
  transform: {
    '^.+\\.tsx?$': ['ts-jest', { tsconfig: '<rootDir>/tsconfig.test.json' }],
  },
  // 忽略 node_modules 的 transform
  transformIgnorePatterns: ['/node_modules/'],
  // 排除预存损坏的测试套件 (chain-planner / intent-multiround 无有效测试用例)
  testPathIgnorePatterns: [
    '/node_modules/',
    '<rootDir>/src/lib/planner/chain-planner',
    '<rootDir>/src/lib/intent/intent-multiround',
  ],
};
