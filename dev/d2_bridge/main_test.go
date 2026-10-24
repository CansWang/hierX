package main

import (
	"io"
	"os"
	"path/filepath"
	"testing"
)

func TestSourceSnapshotIsTheBytesActuallyCompiled(t *testing.T) {
	root := t.TempDir()
	file := filepath.Join(root, "source.d2")
	if err := os.WriteFile(file, []byte("first"), 0600); err != nil {
		t.Fatal(err)
	}
	s := &sourceFS{root: root, files: make(map[string]snapshot)}
	one, err := s.Open("source.d2")
	if err != nil {
		t.Fatal(err)
	}
	one.Close()
	if err := os.WriteFile(file, []byte("changed"), 0600); err != nil {
		t.Fatal(err)
	}
	two, err := s.Open("source.d2")
	if err != nil {
		t.Fatal(err)
	}
	defer two.Close()
	data, err := io.ReadAll(two)
	if err != nil || string(data) != "first" {
		t.Fatalf("snapshot changed: %q, %v", data, err)
	}
	if _, err := s.Open("../outside"); err == nil {
		t.Fatal("outside import accepted")
	}
}
