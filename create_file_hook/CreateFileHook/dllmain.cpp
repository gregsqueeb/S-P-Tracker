// dllmain.cpp : Definiert den Einstiegspunkt für die DLL-Anwendung.
#include "stdafx.h"

#include <stdlib.h>
#include <stdio.h>

#include <string>
#include <algorithm>

#include "mhook-lib/mhook.h"

typedef HANDLE(WINAPI *_CreateFileW)(LPCWSTR , DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE );

static _CreateFileW TrueCreateFileW = (_CreateFileW)GetProcAddress(LoadLibrary(L"kernel32.dll"), "CreateFileW");
static FILE *logFile = NULL;
static std::wstring filter_prefix;
static BOOL hooked = FALSE;

// My Fake CreateFile
static HANDLE WINAPI MyCreateFileW(LPCWSTR lpFileName, DWORD dwDesiredAccess, DWORD dwShareMode, LPSECURITY_ATTRIBUTES lpSecurityAttributes, DWORD dwCreationDisposition, DWORD dwFlagsAndAttributes, HANDLE hTemplateFile)
{
	HANDLE res = TrueCreateFileW(lpFileName, dwDesiredAccess, dwShareMode, lpSecurityAttributes, dwCreationDisposition, dwFlagsAndAttributes, hTemplateFile);
	if (logFile && res != INVALID_HANDLE_VALUE)
	{	
		std::wstring fn = lpFileName;
		std::replace(fn.begin(), fn.end(), L'\\', L'/');
		if (fn.find(filter_prefix) == 0)
		{
			std::string a = "";
			if (dwDesiredAccess & GENERIC_READ)
			{
				a += 'r';
			}
			if (dwDesiredAccess & GENERIC_WRITE)
			{
				a += 'w';
			}
			fprintf(logFile, "%s: %ws\n", a.c_str(), lpFileName, dwDesiredAccess, dwShareMode, dwCreationDisposition, dwFlagsAndAttributes);
			fflush(logFile);
		}
	}
	return res;
}

extern "C" __declspec(dllexport) void __cdecl StartLogging(LPCWSTR filename, LPCWSTR prefix)
{
	if (logFile) fclose(logFile);
	logFile = _wfopen(filename, L"w+");
	filter_prefix = prefix;
	std::replace(filter_prefix.begin(), filter_prefix.end(), L'\\', L'/');
}

BOOL APIENTRY DllMain( HMODULE hModule,
                       DWORD  ul_reason_for_call,
                       LPVOID lpReserved
					 )
{
	switch (ul_reason_for_call)
	{
	case DLL_PROCESS_ATTACH:
		{
			hooked = Mhook_SetHook((PVOID*)&TrueCreateFileW, MyCreateFileW);
			if (!hooked)
			{
				if (logFile) fprintf(logFile, "Mhook_SetHook fail!\n");
			}
			else
			{
				if (logFile) fprintf(logFile, "Successfully hooked CreateFileW\n");
			}
		}
		break;
	case DLL_PROCESS_DETACH:
		if (hooked)
		{
			BOOL ok = Mhook_Unhook((PVOID*)&TrueCreateFileW);
			if (ok) 
			{
				if (logFile) fprintf(logFile, "Successfully unhooked CreateFileW\n");
			}
			else
			{
				if (logFile) fprintf(logFile, "Error unhooking CreateFileW\n");
			}
		}
		break;
	case DLL_THREAD_ATTACH:
	case DLL_THREAD_DETACH:
		break;
	}
	return TRUE;
}
