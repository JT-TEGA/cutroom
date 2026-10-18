// Tests for cutroom/effect-returns (run by `npm run lint`, so `npm run build` runs them too).
import tsParser from "@typescript-eslint/parser"
import { RuleTester } from "eslint"
import rule from "./effect-returns.js"

const tester = new RuleTester({
  languageOptions: { parser: tsParser, ecmaVersion: "latest", sourceType: "module", parserOptions: { ecmaFeatures: { jsx: true } } },
})

tester.run("effect-returns", rule, {
  valid: [
    "useEffect(() => { el.scrollTop = 0 }, [])",
    "useEffect(() => { if (!ok) return; start() }, [ok])",
    "useEffect(() => { const t = setInterval(tick, 1000); return () => clearInterval(t) }, [])",
    "useEffect(() => { const ws = open(); return function cleanup() { ws.close() } }, [])",
    "useEffect(() => { const off = subscribe(); return off }, [])",
    "useEffect(() => () => flushRef.current(), [])",
    "useEffect(() => { const load = async () => { return await fetch(url) }; load() }, [url])",
    "useEffect(() => { items.forEach((x) => { return x.id }) }, [items])",
    "React.useLayoutEffect(() => { measure() })",
    "useMemo(() => compute(), [a])",
    "useEffect(handler, [])",
  ],
  invalid: [
    { code: "useEffect(() => el.scrollTo({ top: 0 }), [path])", errors: [{ messageId: "expression" }] },
    { code: "useEffect(() => setValue(name), [name])", errors: [{ messageId: "expression" }] },
    { code: "useEffect(() => ws.close())", errors: [{ messageId: "expression" }] },
    { code: "useEffect(async () => { await load() }, [])", errors: [{ messageId: "async" }] },
    { code: "useEffect(() => { return setTimeout(go, 900) }, [])", errors: [{ messageId: "value" }] },
    { code: "useEffect(() => { if (x) return store.subscribe(l); }, [x])", errors: [{ messageId: "value" }] },
    { code: "useLayoutEffect(() => { return fetch(url).then(r => r.json()) })", errors: [{ messageId: "value" }] },
    { code: "React.useEffect(() => { return null })", errors: [{ messageId: "value" }] },
  ],
})

console.log("effect-returns rule: all cases pass")
