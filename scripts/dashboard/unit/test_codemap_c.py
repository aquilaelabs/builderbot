"""bb map's C and C++ scanner (B544, report #74 from Shebang-DevBoard): a
function is its header at file, namespace or class level, a type is
`struct|union|enum|class NAME {` or a typedef's name, a prototype is
neither and is no call, calls are made inside functions, and a JNI
implementation is indexed under the Kotlin or Java method it implements.
And the python scanner counts a function handed on as `module.name` (B543)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import codemap  # noqa: E402

C = r'''
#include <jni.h>
#define LOG(...) __android_log_print(ANDROID_LOG_INFO, "x", __VA_ARGS__)

struct whisper_context;                       /* a declaration, not a type */
typedef struct { int a; } pair_t;

enum ggml_log_level { LOG_NONE, LOG_WARN };

WHISPER_API int whisper_full(struct whisper_context * ctx, int n);

/* Says what the logger does. */
static void log_to_logcat(enum ggml_log_level level, const char * text, void * user) {
    if (level >= LOG_WARN) __android_log_print(level, "whisper", "%s", text);
}

JNIEXPORT jlong JNICALL
Java_dev_shebang_devboard_voice_Whisper_nativeInit(JNIEnv *env, jclass cls, jstring path) {
    whisper_log_set(log_to_logcat, NULL);
    struct whisper_context * ctx = whisper_init((const char *) "a{b}c");
    for (int i = 0; i < 3; i++) { whisper_free(ctx); }
    return (jlong) ctx;
}
'''

CPP = r'''
namespace ns {
class Model : public Base {
public:
    Model(int n) : n_(n), name_("m") { setup(n); }
    int size() const override { return helper(n_); }
private:
    int n_;
};
int Model::load(const char * p) noexcept {
    auto f = [&](int x) { return x + 1; };
    return f(open(p));
}
}  // namespace ns
extern "C" {
int c_api(void) { return ns::Model(1).size(); }
}
'''


def scan(text, name="x.c"):
    s = codemap.Sink(name)
    codemap.scan_c(text, s)
    return s


class CScanner(unittest.TestCase):
    def test_functions_and_types_and_nothing_else(self):
        s = scan(C)
        got = sorted((d["kind"], d["name"]) for d in s.defs)
        self.assertEqual(got, [("class", "ggml_log_level"), ("class", "pair_t"), ("decl", "whisper_full"),
                               ("def", "Java_dev_shebang_devboard_voice_Whisper_nativeInit"),
                               ("def", "log_to_logcat"), ("jni", "nativeInit"), ("macro", "LOG")])
        log = next(d for d in s.defs if d["name"] == "log_to_logcat")
        self.assertEqual((log["line"], log["end"]), (13, 15))

    def test_the_rare_forms_report_85_named(self):
        # K&R, a function returning a function pointer, and an explicit
        # specialization beside its primary template (B575).
        s = scan("int\nkr_style(a, b)\n int a; int b;\n{ return helper(a + b); }\n"
                 "int (*returns_fp(void))(int, void *) { return 0; }\n"
                 "static int caller(void) { return kr_style(1, 2); }\n")
        defs = {d["name"]: d["line"] for d in s.defs if d["kind"] == "def"}
        self.assertEqual(defs, {"kr_style": 2, "returns_fp": 5, "caller": 6})
        self.assertIn(("helper", "kr_style"), {(c["name"], c["caller"]) for c in s.calls})
        s = scan("template <typename T> T tmax(T a, T b) { return a; }\n"
                 "template <> int tmax<int>(int a, int b) { return a; }\n"
                 "bool operator>(const A& a, const A& b) { return true; }\n", "x.cpp")
        got = sorted((d["name"], d["line"]) for d in s.defs if d["kind"] == "def")
        self.assertEqual(got, [("operator>", 3), ("tmax", 1), ("tmax", 2)])

    def test_calls_are_made_inside_functions_and_a_prototype_is_none(self):
        s = scan(C)
        calls = {(c["name"], c["caller"]) for c in s.calls}
        self.assertIn(("__android_log_print", "log_to_logcat"), calls)
        self.assertIn(("whisper_free", "Java_dev_shebang_devboard_voice_Whisper_nativeInit"), calls)
        self.assertNotIn("whisper_full", {c["name"] for c in s.calls}, "a prototype is not a call")
        self.assertNotIn("for", {c["name"] for c in s.calls})
        self.assertNotIn("whisper_init", {c["name"] for c in s.calls if c["caller"] == "(top level)"})

    def test_a_callback_handed_on_is_passed_by_name(self):
        s = scan(C)
        self.assertTrue(any(p["name"] == "log_to_logcat" and p["line"] == 19 for p in s.passed))

    def test_the_jni_method_is_named_by_its_class(self):
        jni = next(d for d in scan(C).defs if d["kind"] == "jni")
        self.assertEqual((jni["name"], jni["parent"], jni["jni"]),
                         ("nativeInit", "Whisper", "Java_dev_shebang_devboard_voice_Whisper_nativeInit"))
        self.assertEqual(codemap._jni_method("Java_a_b_My_1Class_do_1it"), ("My_Class", "do_it"))
        self.assertIsNone(codemap._jni_method("JavaScript_thing"))

    def test_cpp_classes_methods_constructors_and_qualified_names(self):
        s = scan(CPP, "x.cpp")
        got = sorted((d["kind"], d["parent"], d["name"]) for d in s.defs)
        self.assertEqual(got, [("class", "", "Model"), ("def", "", "c_api"), ("def", "Model", "Model"),
                               ("def", "Model", "load"), ("def", "Model", "size"), ("namespace", "", "ns")])
        calls = {(c["name"], c["caller"]) for c in s.calls}
        self.assertIn(("setup", "Model"), calls)
        self.assertIn(("open", "load"), calls)
        self.assertNotIn("n_", {c["name"] for c in s.calls}, "an initializer list is not a header's name")


class Followup(unittest.TestCase):
    """Report #79 (B554), Shebang-DevBoard's follow-up on the C scanner."""

    def test_an_ifdef_whose_branches_each_open_a_brace_loses_nothing(self):
        s = scan("int f(int a) {\n#ifdef X\n if (a) {\n#else\n if (!a) {\n#endif\n return 1; }\n return 0; }\n"
                 "int g(void) { return 2; }\n")
        got = {d["name"]: (d["line"], d.get("end")) for d in s.defs}
        self.assertEqual(got, {"f": (1, 8), "g": (9, 9)})

    def test_nested_conditionals_keep_their_first_branches(self):
        s = scan("#if A\n#if B\nint a(void) { return 1; }\n#else\nint b(void) {\n#endif\n#elif C\n"
                 "int c(void) {\n#endif\nint d(void) { return 4; }\n")
        self.assertEqual(sorted(d["name"] for d in s.defs), ["a", "d"])

    def test_balanced_later_branches_are_read(self):
        # B805: ggml's SIMD helpers, one whole function per branch of an
        # #if/#elif chain, were missing behind the first branch
        s = scan("#if defined(NEON)\nstatic inline int ld(int x) { return x; }\n#elif defined(AVX)\n"
                 "static inline __m256 ld8(const float *p) {\n  return _mm256_loadu_ps(p);\n}\n"
                 "#else\nstatic inline unsigned char ggml_endian_byte(int i) { return (unsigned char)i; }\n"
                 "#endif\nint after(void) { return 0; }\n")
        self.assertEqual(sorted(d["name"] for d in s.defs), ["after", "ggml_endian_byte", "ld", "ld8"])
        self.assertEqual({d["name"]: d["line"] for d in s.defs}["after"], 10)

    def test_an_unbalanced_inner_branch_is_dropped_and_the_outer_still_read(self):
        s = scan("#if A\nint a(void) {\n#if B\n  if (x) {\n#else\n  if (y) {\n#endif\n  } return 1; }\n"
                 "#else\nint z(void) { return 2; }\n#endif\nint d(void) { return 4; }\n")
        got = {d["name"]: (d["line"], d.get("end")) for d in s.defs}
        self.assertEqual(got, {"a": (2, 8), "z": (10, 10), "d": (12, 12)})

    def test_a_template_with_a_default_is_a_definition(self):
        # B807: the header's = read as an assignment
        s = scan("template <typename T, int N = 0>\nvoid two(T x) { return; }\n"
                 "template <typename T,\n  typename std::enable_if<is_q<T>::value, int>::type = 0>\n"
                 "inline void scale_C(const T * tile) { return; }\nint x = 0;\nint after(void) { return 1; }\n",
                 "a.cpp")
        self.assertEqual(sorted((d["name"], d["line"]) for d in s.defs), [("after", 7), ("scale_C", 5), ("two", 2)])

    def test_a_header_api_is_findable(self):
        s = scan("#define SQUARE(x) ((x) * (x))\n#define MAX 4\nint proto_only(int, int);\n"
                 "typedef struct point { int x; } point_t;\ntypedef int (*callback_fn)(int, void *);\n"
                 "typedef unsigned long ulong;\nextern int g_count;\n", "api.h")
        self.assertEqual(sorted((d["kind"], d["name"]) for d in s.defs),
                         [("class", "point"), ("decl", "proto_only"), ("macro", "MAX"), ("macro", "SQUARE"),
                          ("typedef", "callback_fn"), ("typedef", "point_t"), ("typedef", "ulong")])

    def test_a_variable_made_with_arguments_is_not_a_call(self):
        s = scan("void f(void) {\n  outer::inner::Widget w(3);\n  return g(1);\n}\n", "a.cpp")
        self.assertEqual(sorted(c["name"] for c in s.calls), ["g"])


class AnonymousFunctions(unittest.TestCase):
    """An anonymous `function (` handed to a call owns its body, and the
    first name in it is a call, not the function's name (B545: a WordPress
    functions.php read add_theme_support, $css and echo as functions)."""

    def scan(self, text, name):
        s = codemap.Sink(name)
        codemap.scan_js(text, s)
        return s

    def test_php(self):
        s = self.scan("<?php\nadd_action('init', function () {\n    add_theme_support('x');\n"
                      "    $css = path('s.css');\n    echo esc_html($css);\n});\n"
                      "function aq_setup($x) { return helper($x); }\n", "functions.php")
        self.assertEqual([(d["name"], d["line"], d["end"]) for d in s.defs],
                         [("(anonymous)", 2, 6), ("aq_setup", 7, 7)])
        self.assertEqual({(c["name"], c["caller"]) for c in s.calls},
                         {("add_action", "(top level)"), ("add_theme_support", "(anonymous)"),
                          ("path", "(anonymous)"), ("esc_html", "(anonymous)"), ("helper", "aq_setup")})

    def test_a_function_stored_in_a_file_scope_table_is_passed(self):
        # ggml's type_traits, and C dispatch tables generally (report #83).
        s = scan("typedef void (*fn_t)(void);\n"
                 "static void target_b(void) {}\n"
                 "static void target_c(void) {}\n"
                 "static const struct t tbl[] = {\n"
                 "    { .f = target_b, },\n"
                 "    { .f = (fn_t) target_c, },\n"
                 "};\n"
                 "int other(int a);\n")
        names = {p["name"] for p in s.passed}
        self.assertTrue({"target_b", "target_c"} <= names, names)
        self.assertNotIn("other", names, "a declaration is no pass")

    def test_javascript(self):
        s = self.scan("on('x', function () { doThing(); });\nconst o = { m(a) { z(); } };\n", "a.js")
        self.assertEqual([(d["kind"], d["name"]) for d in s.defs], [("function", "(anonymous)"), ("method", "m")])
        self.assertIn(("doThing", "(anonymous)"), {(c["name"], c["caller"]) for c in s.calls})


class Languages(unittest.TestCase):
    def test_it_says_what_is_read_and_what_is_not(self):
        text = "\n".join(codemap.languages())
        self.assertIn("C and C++: .c .cc .cpp", text)
        self.assertIn(".php", text)
        self.assertIn("anything else is not indexed (.css", text)
        self.assertIn("languages", codemap.VERBS)


class PythonPassedAsAttribute(unittest.TestCase):
    def test_a_module_function_handed_on_is_passed(self):
        s = codemap.Sink("x.py")
        codemap.scan_python("import nodes\nconfigure(node_addr=nodes.ssh_addr_of)\nnodes.other(1)\n", s)
        self.assertTrue(any(p["name"] == "ssh_addr_of" for p in s.passed))
        self.assertFalse(any(p["name"] == "other" for p in s.passed), "a call is not a pass")


if __name__ == "__main__":
    unittest.main()
