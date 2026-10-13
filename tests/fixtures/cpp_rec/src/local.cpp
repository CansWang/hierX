// Function-local classes with the same name in two functions (review round 9): each is reached through a static
// instance and each function returns the size of its own class for the compiler oracle.
int f() { struct L { int a; }; static L inst; return inst.a + (int)sizeof inst; }

int g() { struct L { int a; int b; }; static L inst; return inst.a + (int)sizeof inst; }
