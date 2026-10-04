/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  // 与 tsconfig.json 的 paths "@/*": ["./src/*"] 对齐
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  testMatch: ['<rootDir>/src/**/*.test.ts'],
  // ts-jest 配置：用项目 tsconfig
  transform: {
    '^.+\\.tsx?$': ['ts-jest', { tsconfig: '<rootDir>/tsconfig.json' }],
  },
  // 忽略 node_modules 的 transform
  transformIgnorePatterns: ['/node_modules/'],
};
