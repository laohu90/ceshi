const { mnemonicToAccount } = require('viem/accounts');
const mnemonic = process.argv[2];
const account = mnemonicToAccount(mnemonic, { privateKey: true });

// 仅输出地址
console.log(JSON.stringify([
    {
        address: account.address
    }
]));