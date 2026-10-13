// Two mutually recursive nested types with the SAME unqualified name in one header: (kind, name, file) collides,
// only the qualified identity (A::node vs B::node) orders them deterministically.
#pragma once

struct B;
struct A {
    struct node;
    int a;
};
struct B {
    struct node;
    int b;
};
struct A::node { B::node *peer; int av; };
struct B::node { A::node *peer; int bv; };
