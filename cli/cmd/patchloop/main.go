// Command patchloop is the PatchLoop CLI.
package main

import (
	"os"

	"patchloop-cli/internal/commands"
)

func main() {
	os.Exit(commands.Execute())
}
