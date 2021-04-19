/*
Parser for Valve Data Format, also known as the KeyValues
format: https://developer.valvesoftware.com/wiki/KeyValues
 
Written by soupcan for GoldenEye: Source
 
---------------------------------------------------------------
 
This header provides an easy syntax for reading VDF files.
Usage: ${ReadVDFStr} $outvar vdf_filename key_name
Or...: ${ReadVDFStrMultiple} $outvar vdf_filename key_name index
 
$outvar: The output will be returned to this var.
 
vdf_filename is the path to the VDF file to be read.
 
key_name is the full "path" to the key which you want to read.
It can contain multiple keys and subkeys, delimited by '>'
Note: You can only query keys that do not have any children.
 
Index: If using ${ReadVDFStrMultiple}, it will read the Nth
matching key, unlike ${ReadVDFStr} which will return the 1st.
This is useful for reading multiple values with the same key
name.
 
To use ${ReadVDFStrMultiple}, you can keep querying it with an
incrementing index, until the errors flag is set, indicating
that no more matching keys could be found.
 
If there is an error, the errors flag will be set and the error
message will be copied to $vdfError
*/
 
Var vdfOut ; $outvar
Var vdfError
Var vdfFile ; File name
Var vdfFileHandle ; File handle
Var vdfIndex ; If parsing multiple keys, which index are we looking for?
             ; This is simply the number of matching keys we've hit so far.
Var vdfCurIndex ; Which index are we currently on?
Var vdfKey ; Full "path" to the key/subkey of the VDF
Var vdfCurrentKey ; Current VDF key being processed
Var vdfLevel ; Current "level" (how many curley brackets deep)
Var vdfDepth ; Depth/level of the target key
Var vdfToken ; The current token returned by the vdfGetNextToken function.
Var vdfBracket ; Used by vdfGetNextToken to signal to vdfMain when an opening or
               ; closing bracket is found. We do it this way instead of using
               ; vdfToken, because a quoted curley bracket could otherwise fool
               ; our parser.
 
 
!define ReadVDFStr "!insertmacro ReadVDFStr"
!define ReadVDFStrMultiple "!insertmacro ReadVDFStrMultiple"
 
!macro ReadVDFStr outvar filename key
	StrCpy $vdfFile "${filename}"
	StrCpy $vdfKey "${key}"
	StrCpy $vdfIndex ''
 
	Call vdfMain
	StrCpy "${outvar}" $vdfOut
!macroend
 
!macro ReadVDFStrMultiple outvar filename key index
	StrCpy $vdfFile "${filename}"
	StrCpy $vdfKey "${key}"
	StrCpy $vdfIndex "${index}"
 
	Call vdfMain
	StrCpy "${outvar}" $vdfOut
!macroend
 
; Get depth of the provided $vdfKey and stores it in $vdfDepth
; Depth starts at 0, e.g. "ges_version" is 0 while "ges_version>text" is 1
Function vdfGetKeyDepth
	Push $0 ; $0 = length of string
	Push $1 ; $1 = numeric index of char in string
	Push $2 ; $2 = current char
 
	StrLen $0 $vdfKey
	StrCpy $vdfDepth 0
	StrCpy $1 1
 
	ReadNextChar:
		; Read char at index ($1) of $vdfKey and store it in $2
		StrCpy $2 $vdfKey 1 $1
 
		; If current char $2 == '>', increment $vdfDepth
		StrCmp $2 ">" +1 NoMatch
			IntOp $vdfDepth $vdfDepth + 1
		NoMatch:
		; Increment index
		IntOp $1 $1 + 1
 
		; If index >= StrLen, return
		; Otherwise, restart loop
		IntCmp $0 $1 +1 +1 ReadNextChar
 
		Pop $2
		Pop $1
		Pop $0
 
FunctionEnd
 
; This function gets the VDF key at $vdfLevel
; and stores it in $vdfCurrentKey
Function vdfGetCurrentKey
	Push $0 ; $0 = length of string
	Push $1 ; $1 = numeric index of char in string
	Push $2 ; $2 = current char
	Push $3 ; $3 = current level being processed
 
	StrLen $0 $vdfKey
	StrCpy $vdfCurrentKey ''
	StrCpy $1 0
	StrCpy $3 0
 
	ReadNextChar:
		; Read char at index ($1) of $vdfKey and store it in $2
		StrCpy $2 $vdfKey 1 $1
 
		; If we're at our target level...
		StrCmp $3 $vdfLevel +1 NotEqual
			; Return immediately if current char is >
			StrCmp $2 ">" RReturn +1
			; Otherwise, copy current char $2 to $vdfCurrentKey
			StrCpy $vdfCurrentKey "$vdfCurrentKey$2"
		NotEqual:
 
		; If current char $2 == '>', increment level
		StrCmp $2 ">" +1 NoMatch
			IntOp $3 $3 + 1
		NoMatch:
		; Increment index
		IntOp $1 $1 + 1
 
		; If index >= StrLen, return
		; Otherwise, restart loop
		IntCmp $0 $1 +1 +1 ReadNextChar
 
		RReturn:
 
		Pop $3
		Pop $2
		Pop $1
		Pop $0
FunctionEnd
 
; This function gets the next token. A token is any text in the file,
; including key names, values and brackets. Comments are skipped.
;
; This function handles double-quotes for keys/values with spaces in
; them. It also handles the escape sequences \n, \t, \\, and \".
Function vdfGetNextToken
	Var /GLOBAL vdfJunk ; /dev/null
	Var /GLOBAL vdfCurrentChar ; current char in file
	Var /GLOBAL vdfIsQuoted ; Are we currently in an open double quote?
	Var /GLOBAL vdfIsEscaped ; Was the previous character the escape character '\'?
	Var /GLOBAL vdfIsLastCharFwdSlash ; Is the previous char an (unquoted) forward slash? Two of these in a row is a comment.
 
	StrCpy $vdfToken ''
	StrCpy $vdfBracket ''
	StrCpy $vdfCurrentChar ''
	StrCpy $vdfIsQuoted ''
	StrCpy $vdfIsEscaped ''
	StrCpy $vdfIsLastCharFwdSlash ''
 
	ReadNextChar:
		; Read the char into $vdfCurrentChar and advance offset by 1
		FileRead $vdfFileHandle $vdfCurrentChar 1
		IfErrors ReachedEOF
 
		; If we are in an open quote, don't check for comments
		StrCmp $vdfIsQuoted '' +1 CommentEnd
 
			; If this char, and previous char, were forward slashes
			; skip to next line as this is a comment
			StrCmp $vdfCurrentChar '/' +1 NotFSlash
				; If the last char was also a forward slash, skip to next line
				; Also unset the var since we will want a fresh start for the next line.
				StrCmp $vdfIsLastCharFwdSlash '1' +1 NotFSlash
					; Calling FileRead without a maxlen will take us to the next line.
					; We don't care about the output so we just write to our junk var
					FileRead $vdfFileHandle $vdfJunk
					StrCpy $vdfIsLastCharFwdSlash ''
					; Subtract last char (fwd slash) from vdfToken
					StrCpy $vdfToken $vdfToken -1
					Goto ReadNextChar
 
			NotFSlash:
 
			; Set the vdfIsLastCharFwdSlash variable
			StrCpy $vdfIsLastCharFwdSlash ''
			StrCmp $vdfCurrentChar '/' +1 StillNotAFSlash
				StrCpy $vdfIsLastCharFwdSlash 1
			StillNotAFSlash:
 
		CommentEnd:
 
		; Opening/closing brackets --
		; These are not supposed to be at the beginning or end of another token
		; unless it's quoted. So, if we find one while unquoted, we return its
		; result immediately.
		StrCmp $vdfIsQuoted '' +1 SkipBracket
			StrCmp $vdfCurrentChar '{' +1 NotOpeningBracket
				StrCmp $vdfToken '' +1 ReturnCurrentToken
					StrCpy $vdfBracket '{'
					Return
 
			NotOpeningBracket:
				; Processing for closing bracket
				StrCmp $vdfCurrentChar '}' +1 SkipBracket
					StrCmp $vdfToken '' +1 ReturnCurrentToken
						StrCpy $vdfBracket '}'
						Return
 
			ReturnCurrentToken:
				; Rewind back 1 char, to make sure we don't
				; skip the bracket next time
				FileSeek $vdfFileHandle -1 CUR
				Return
 
		SkipBracket:
 
		; Skip all quote parsing if we're escaped
		StrCmp $vdfIsEscaped '' +1 SkipAllQuoteParsing
 
		; If current char is a quote, toggle the $vdfIsQuoted flag 
		StrCmp $vdfCurrentChar '"' +1 NotQuote
			StrCmp $vdfIsQuoted '' +1 IsCurrentlyQuoted
				StrCpy $vdfIsQuoted 1
				Goto QuoteFlagEnd
			IsCurrentlyQuoted:
				StrCpy $vdfIsQuoted ''
 
		QuoteFlagEnd:
 
		; If current char is a quote, and the $vdfIsQuoted flag is
		; unset (meaning we're ending a quote), return
		; 
		; If current char is a quote, and the $vdfIsQuoted flag is
		; set (meaning we're beginning a quote), goto ReadNextChar
		; if we haven't read a token yet. If we have, return.
 
		StrCmp $vdfCurrentChar '"' +1 NotQuote
			StrCmp $vdfIsQuoted '' +1 IsOpeningQuote
				Return
			IsOpeningQuote:
				StrCmp $vdfToken '' ReadNextChar
				Return
 
		NotQuote:
 
		; If current char is a whitespace, and we are NOT in an open
		; quote block, read next char UNLESS we already wrote something
		; into $vdfToken
 
		; Skip if quoted.
		StrCmp $vdfIsQuoted '' +1 SkipWhitespace
 
			; Space
			StrCmp $vdfCurrentChar " " CharIsWhitespace +1
			; Carriage return
			StrCmp $vdfCurrentChar "$\r" CharIsWhitespace +1
			; Newline
			StrCmp $vdfCurrentChar "$\n" CharIsWhitespace +1
			; Tab
			StrCmp $vdfCurrentChar "$\t" CharIsWhitespace +1
 
			Goto SkipWhitespace
 
			CharIsWhitespace:
				StrCmp $vdfToken '' ReadNextChar +1
					Return
 
		SkipWhitespace:
 
		SkipAllQuoteParsing:
 
		; Handle escape sequences if vdfIsEscaped is set
		StrCmp $vdfIsEscaped '' ParseEscapeEnd
			; Newline
			StrCmp $vdfCurrentChar "n" +1 Tab
				StrCpy $vdfCurrentChar "$\n"
				Goto RemoveLastChar
 
			Tab:
			StrCmp $vdfCurrentChar "t" +1 Backslash
				StrCpy $vdfCurrentChar "$\t"
				Goto RemoveLastChar
 
			Backslash:
			StrCmp $vdfCurrentChar "\" +1 Quote
				StrCpy $vdfCurrentChar '\'
				Goto RemoveLastChar
 
			Quote:
			StrCmp $vdfCurrentChar '"' +1
				StrCpy $vdfCurrentChar '"'
				Goto RemoveLastChar
 
			; If the char isn't a recognized escape sequence, finish
			Goto ParseEscapeEnd
 
		RemoveLastChar:
			; Remove backslash
			StrCpy $vdfToken $vdfToken -1
 
		ParseEscapeEnd:
 
		; Is this char a back slash?
		StrCmp $vdfCurrentChar '\' +1 Unescape
			; Set vdfIsEscaped, but only if isEscaped isn't already set
			; if it is, unset it
			StrCmp $vdfIsEscaped "" +1 Unescape
				StrCpy $vdfIsEscaped '1'
				Goto SetEscapedEnd
		Unescape:
			StrCpy $vdfIsEscaped ''
		SetEscapedEnd:
 
		StrCpy $vdfToken "$vdfToken$vdfCurrentChar"
 
		Goto ReadNextChar
 
	ReachedEOF:
		SetErrors
		Return
 
FunctionEnd
 
!macro vdfError text
	StrCpy $vdfOut ''
	StrCpy $vdfError "${text}"
	StrCpy $vdfErrorState 1
	Goto RReturn
!macroend
 
Function vdfMain
	Var /GLOBAL vdfFileSize ; file size of input file
	Var /GLOBAL vdfPreExistingErrorState ; error state when function was called
	Var /GLOBAL vdfErrorState ; whether to SetErrors at the end of the function, regardless of pre-existing error state
	Var /GLOBAL vdfIsValue ; set if processing a value. this is so we know if we're processing a value, or some other token type.
	Var /GLOBAL vdfCurLevel ; current level of the token being processed
 
	StrCpy $vdfPreExistingErrorState ''
	StrCpy $vdfErrorState ''
	StrCpy $vdfError ''
	StrCpy $vdfFileSize ''
	StrCpy $vdfLevel 0
	StrCpy $vdfIsValue ''
	StrCpy $vdfCurLevel 0
	StrCpy $vdfCurIndex 0
 
	; Get current error state, to restore it later.
	StrCpy $vdfPreExistingErrorState 0
	IfErrors +1 NoErrors 
		StrCpy $vdfPreExistingErrorState 1
	NoErrors:
	ClearErrors
 
	IfFileExists $vdfFile FileExists
		!insertmacro vdfError "File doesn't exist."
	FileExists:
 
	FileOpen $vdfFileHandle $vdfFile r
 
	; Get file size
	FileSeek $vdfFileHandle 0 END $vdfFileSize
 
	; Check that file isn't more than 4MiB in length
	IntCmp $vdfFileSize 4194304 FileSizeOk FileSizeOk
		!insertmacro vdfError "File too large."
	FileSizeOk:
 
	; Rewind back to starting position
	FileSeek $vdfFileHandle 0
 
	Call vdfGetKeyDepth ; Initializes $vdfDepth
	Call vdfGetCurrentKey ; Sets $vdfCurrentKey to its initial value
 
	GetToken:
		ClearErrors
		Call vdfGetNextToken
		IfErrors +1 NoParserErrors
			!insertmacro vdfError "Reached EOF without finding key."
 
		NoParserErrors:
 
		StrCmp $vdfBracket '{' +1 SkipLevelUp
			IntOp $vdfCurLevel $vdfCurLevel + 1
			StrCpy $vdfIsValue ''
			Goto GetToken
 
		SkipLevelUp:
 
		StrCmp $vdfBracket '}' +1 SkipLevelDn
			IntOp $vdfCurLevel $vdfCurLevel - 1
			StrCpy $vdfIsValue ''
			Goto GetToken
 
		SkipLevelDn:
 
		; If this is a value, rather than key, get next token
		StrCmp $vdfIsValue '' TokenIsKey
			StrCpy $vdfIsValue ''
			Goto GetToken
 
		TokenIsKey:
 
		; Set isValue, so that next token isn't treated like a key
		StrCpy $vdfIsValue 1
 
		; Get next token if we arent at our target depth for our next key
		StrCmp $vdfCurLevel $vdfLevel +1 GetToken
 
		; If the token == our key name, get the next token (the value)
		StrCmp $vdfToken $vdfCurrentKey +1 GetToken
			Call vdfGetNextToken
			StrCpy $vdfIsValue ''
 
			; If current level == key depth, treat next token like it's the value we're looking for
			StrCmp $vdfLevel $vdfDepth +1 ExpectingBracket
				; Check if we actually got a value, or a bracket
				StrCmp $vdfBracket '' GotValue
					!insertmacro vdfError "Got '$vdfBracket', expecting value string"
				GotValue:
					; Check if we're reading multiple keys, or just this one...
					StrCmp $vdfIndex '' ReturnToken
						; Check if we're at our destination index
						StrCmp $vdfIndex $vdfCurIndex ReturnToken
							; And if we aren't, increment our current index and try again
							IntOp $vdfCurIndex $vdfCurIndex + 1
							Goto GetToken
 
					ReturnToken:
						StrCpy $vdfOut $vdfToken
						Goto RReturn
 
			; Otherwise, we're expecting an opening bracket...
			ExpectingBracket:
				; Increment levels and depth, get next key
				StrCmp $vdfBracket '{' +1 NoBracketMatch
					IntOp $vdfCurLevel $vdfCurLevel + 1
					IntOp $vdfLevel $vdfLevel + 1
					StrCpy $vdfIsValue ''
					Call vdfGetCurrentKey
					Goto GetToken
 
				NoBracketMatch:
					!insertmacro vdfError "Got '$vdfBracket$vdfToken', expecting '{'"
 
 
 
	RReturn:
		FileClose $vdfFileHandle
 
		; Restore prior error state
		ClearErrors
		StrCmp $vdfPreExistingErrorState 1 +1 DontSetErrors
			SetErrors
		DontSetErrors:
 
		; If our internal error flag was set, then set errors
		; regardless of prior error state.
		StrCmp $vdfErrorState "" ReallyDontSetErrors
			SetErrors
		ReallyDontSetErrors:
 
FunctionEnd
