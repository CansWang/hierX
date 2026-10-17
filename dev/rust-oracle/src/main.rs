//! Independent source boundaries; this tool is never used by hx at runtime.
use proc_macro2::Span;
use serde_json::{Value, json};
use syn::{spanned::Spanned, visit::Visit};

struct Inventory<'a> { source: &'a str, calls: Vec<Value>, functions: Vec<Value>, macros: Vec<Value> }
impl Inventory<'_> {
    fn position(&self, span: Span) -> Value {
        let p = span.start();
        json!({"line": p.line, "column": p.column})
    }
    fn text(&self, span: Span) -> String {
        let a = span.start(); let b = span.end();
        let lines: Vec<&str> = self.source.split_inclusive('\n').collect();
        // proc_macro2 reports character columns outside compiler procedural macros.
        let offset = |line: usize, column: usize| {
            let prefix = lines.iter().take(line - 1).map(|s| s.len()).sum::<usize>();
            prefix + lines[line - 1].char_indices().nth(column).map(|(i, _)| i).unwrap_or(lines[line - 1].len())
        };
        let start = offset(a.line, a.column);
        let end = offset(b.line, b.column);
        self.source.get(start..end).unwrap_or("").to_string()
    }
}
impl<'ast> Visit<'ast> for Inventory<'_> {
    fn visit_item_fn(&mut self, f: &'ast syn::ItemFn) {
        self.functions.push(json!({"name": f.sig.ident.to_string(), "start": self.position(f.span()), "end": self.position(f.block.span())}));
        syn::visit::visit_item_fn(self, f);
    }
    fn visit_expr_call(&mut self, call: &'ast syn::ExprCall) {
        let span = if let syn::Expr::Path(p) = &*call.func { p.path.segments.last().unwrap().ident.span() } else { call.func.span() };
        self.calls.push(json!({"start": self.position(call.func.span()), "name_start": self.position(span),
            "args": call.args.iter().map(|a| self.text(a.span())).collect::<Vec<_>>()}));
        syn::visit::visit_expr_call(self, call);
    }
    fn visit_expr_method_call(&mut self, call: &'ast syn::ExprMethodCall) {
        self.calls.push(json!({"start": self.position(call.method.span()), "name": call.method.to_string(),
            "args": call.args.iter().map(|a| self.text(a.span())).collect::<Vec<_>>()}));
        syn::visit::visit_expr_method_call(self, call);
    }
    fn visit_macro(&mut self, mac: &'ast syn::Macro) {
        self.macros.push(json!({"name": mac.path.segments.last().unwrap().ident.to_string(),
            "start": self.position(mac.span()), "end": self.position_end(mac.span())}));
        syn::visit::visit_macro(self, mac);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_slices_and_sites_cover_unicode_and_qualified_calls() {
        let source = "fn f() { let é = \"😀\"; Type::call(\"é\", |a, b| a + b); join!(task.call()); }";
        let syntax = syn::parse_file(source).unwrap();
        let mut visitor = Inventory { source, calls: vec![], functions: vec![], macros: vec![] };
        visitor.visit_file(&syntax);
        assert_eq!(visitor.calls[0]["args"], json!(["\"é\"", "|a, b| a + b"]));
        assert_eq!(visitor.calls[0]["start"]["column"], source.find("Type").map(|b| source[..b].chars().count()).unwrap());
        assert_eq!(visitor.calls[0]["name_start"]["column"], source.find("call").map(|b| source[..b].chars().count()).unwrap());
        assert_eq!(visitor.macros[0]["name"], "join");
    }
}
impl Inventory<'_> {
    fn position_end(&self, span: Span) -> Value {
        let p = span.end();
        json!({"line": p.line, "column": p.column})
    }
}
fn main() {
    for file in std::env::args().skip(1) {
        let source = std::fs::read_to_string(&file).expect("read Rust source");
        let syntax = syn::parse_file(&source).expect("parse Rust source");
        let mut visitor = Inventory { source: &source, calls: vec![], functions: vec![], macros: vec![] };
        visitor.visit_file(&syntax);
        println!("{}", json!({"file": file, "calls": visitor.calls, "functions": visitor.functions, "macros": visitor.macros}));
    }
}
