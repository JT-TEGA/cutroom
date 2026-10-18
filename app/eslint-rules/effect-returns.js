/**
 * cutroom/effect-returns: an effect may return nothing or a cleanup function, never anything else.
 *
 * React keeps whatever an effect returns and calls it when the component unmounts (or before the effect re-runs).
 * Return a Promise, a timer id or a stray value and the app crashes later with "destroy is not a function". It hides
 * well: `useEffect(() => el.scrollTo({ top: 0 }), [path])` looked harmless until Chrome made scrollTo() return a
 * Promise. So this rule reports:
 *
 *   useEffect(async () => ...)                  async callbacks (they return a Promise)
 *   useEffect(() => doSomething())              a one-line body: its value is returned (use braces)
 *   useEffect(() => { ...; return x.y() })      returning anything but a function or a variable holding one
 *
 * Allowed: block bodies with no return value, `return () => ...`, `return function () {}`, `return cleanup`
 * (an identifier), and `useEffect(() => () => cleanup())`.
 */
const EFFECTS = new Set(["useEffect", "useLayoutEffect", "useInsertionEffect"])
const FUNCTIONS = new Set(["ArrowFunctionExpression", "FunctionExpression"])
const SCOPES = new Set([...FUNCTIONS, "FunctionDeclaration", "ClassDeclaration", "ClassExpression"])

function hookName(callee) {
  if (callee.type === "Identifier") return callee.name
  if (callee.type === "MemberExpression" && !callee.computed && callee.property.type === "Identifier") return callee.property.name
  return null
}

/** The return statements that belong to `fn` itself (not to functions nested in it). */
function ownReturns(fn) {
  const out = []
  const visit = (node, top) => {
    if (!node || typeof node.type !== "string") return
    if (!top && SCOPES.has(node.type)) return
    if (node.type === "ReturnStatement") out.push(node)
    for (const key of Object.keys(node)) {
      if (key === "parent") continue
      const value = node[key]
      if (Array.isArray(value)) value.forEach((v) => visit(v, false))
      else if (value && typeof value.type === "string") visit(value, false)
    }
  }
  visit(fn.body, true)
  return out
}

export default {
  meta: {
    type: "problem",
    docs: { description: "Effects must return nothing or a cleanup function" },
    schema: [],
    messages: {
      async:
        "{{hook}} callbacks can't be async: they return a Promise, which React later calls as the cleanup " +
        "(\"destroy is not a function\"). Define an async function inside the effect and call it.",
      expression:
        "This {{hook}} returns the value of its one-line body, and React treats whatever comes back as the cleanup " +
        "function. Wrap the body in braces: {{hook}}(() => { ... }).",
      value:
        "{{hook}} may only return a cleanup function (or nothing). Returning a value here crashes on unmount " +
        "(\"destroy is not a function\").",
    },
  },
  create(context) {
    return {
      CallExpression(node) {
        const hook = hookName(node.callee)
        if (!EFFECTS.has(hook)) return
        const fn = node.arguments[0]
        if (!fn || !FUNCTIONS.has(fn.type)) return
        if (fn.async) return context.report({ node: fn, messageId: "async", data: { hook } })
        if (fn.body.type !== "BlockStatement") {
          if (!FUNCTIONS.has(fn.body.type)) context.report({ node: fn.body, messageId: "expression", data: { hook } })
          return
        }
        for (const ret of ownReturns(fn)) {
          const arg = ret.argument
          if (arg && !FUNCTIONS.has(arg.type) && arg.type !== "Identifier")
            context.report({ node: ret, messageId: "value", data: { hook } })
        }
      },
    }
  },
}
