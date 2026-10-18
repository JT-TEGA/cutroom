import tsParser from "@typescript-eslint/parser"
import reactHooks from "eslint-plugin-react-hooks"
import effectReturns from "./eslint-rules/effect-returns.js"

// Kept small on purpose: the rules here catch crashes TypeScript can't see. Type errors are tsc's job.
export default [
  { ignores: ["dist/**", "node_modules/**", "src/api/schema.d.ts"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { cutroom: { rules: { "effect-returns": effectReturns } }, "react-hooks": reactHooks },
    rules: {
      "cutroom/effect-returns": "error", // effects return nothing or a cleanup function ("destroy is not a function")
      "react-hooks/rules-of-hooks": "error", // hooks unconditionally, in the same order every render
    },
  },
]
