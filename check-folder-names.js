/* eslint-disable */

import fs from 'node:fs'
import path from 'node:path'

const isKebabCase = (str) => {
  const kebabCaseRegex = /^[a-z()[\]]+(-[a-z()[\]]+)*$/

  return kebabCaseRegex.test(str)
}

let hasError = false

const checkFolderNames = (directory, ignoreList = []) => {
  const files = fs.readdirSync(directory)

  const filteredFiles = files.filter(
    (fileItem) => !ignoreList.includes(fileItem),
  )

  for (const file of filteredFiles) {
    const filePath = path.join(directory, file)

    if (fs.statSync(filePath).isDirectory()) {
      if (!isKebabCase(file) && !ignoreList.includes(file)) {
        hasError = true

        console.log(`Folder name not in kebab-case: ${filePath}`)
      }

      // Recursively check subdirectories
      checkFolderNames(filePath, ignoreList)
    }
  }

  if (hasError) {
    const errorMessage = 'All folders and files must be in kebab-case!'

    console.error(errorMessage)
    process.exit(1)
  }
}

// List of folder names to ignore
const foldersToIgnore = [
  'node_modules',
  '.next',
  '.storybook',
  '.idea',
  '.helm',
  '.git',
  '.husky',
  '.vscode',
  '.vite',
  'dist',
  '.tanstack',
]

// Start the check from the current working directory (root of your project)
const rootDirectory = process.cwd()
checkFolderNames(rootDirectory, foldersToIgnore)
